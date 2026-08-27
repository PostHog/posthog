import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus} from '../src/file'
import {compareWithMergeCommit} from '../src/shadow'

const cp = jest.requireMock('child_process') as {execFile: jest.Mock}

jest.mock('child_process', () => ({execFile: jest.fn()}))
jest.mock('@actions/core', () => ({info: jest.fn(), warning: jest.fn(), startGroup: jest.fn(), endGroup: jest.fn()}))

const HEAD = 'a'.repeat(40)
const GIT_DIR = '/tmp/runner/paths-filter-shadow.git'
const PAST_ANY_BUDGET_MS = 120000

type ExecFileArgs = [string, string[], {signal: AbortSignal}, (error: Error | null, stdout: string) => void]

const pullRequest = {number: 42, head: {sha: HEAD}} as PullRequest

describe('shadow merge-commit comparison', () => {
  beforeEach(() => {
    process.env.RUNNER_TEMP = '/tmp/runner'
    process.env.GITHUB_SERVER_URL = 'https://github.com'
    process.env.GITHUB_REPOSITORY = 'PostHog/posthog'
    cp.execFile.mockReset()
  })

  // A --depth or --filter fetch rewrites the shallow boundary and promisor config of
  // whichever repository it runs in. Steps after this action read history from the
  // workspace checkout: ci-dagster and ci-e2e-playwright resolve
  // `git merge-base HEAD^2 origin/<base>` there, and an empty merge base silently
  // drops their schema cache. So every call has to name the scratch git dir.
  test('never runs git against the job workspace', async () => {
    for (const stdout of ['', '', HEAD, 'a.ts\0']) {
      cp.execFile.mockImplementationOnce((...args: ExecFileArgs) => args[3](null, stdout))
    }

    const result = await compareWithMergeCommit([{filename: 'a.ts', status: ChangeStatus.Modified}], pullRequest)

    expect(result.verdict).toBe('match')
    const calls = cp.execFile.mock.calls.map(c => c[1] as string[])
    expect(calls[0]).toEqual(['init', '--bare', '--quiet', GIT_DIR])
    for (const argv of calls.slice(1)) {
      expect(argv.slice(0, 2)).toEqual(['--git-dir', GIT_DIR])
    }
  })

  // The budget only bounds the job if it also stops the git process. An exec that returns
  // no handle on the child leaves the fetch running, and the action's process stays open
  // until git exits, which is the wall-clock cost the budget exists to prevent.
  test('stops git when the budget expires', async () => {
    cp.execFile.mockImplementation(() => undefined)
    jest.useFakeTimers()

    const pending = compareWithMergeCommit([], pullRequest)
    await jest.advanceTimersByTimeAsync(PAST_ANY_BUDGET_MS)
    const result = await pending

    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toContain('budget')
    const [, , options] = cp.execFile.mock.calls[0] as ExecFileArgs
    expect(options.signal.aborted).toBe(true)
    jest.useRealTimers()
  })
})

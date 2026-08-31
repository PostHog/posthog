import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus} from '../src/file'
import {compareWithMergeCommit} from '../src/shadow'

const cp = jest.requireMock('child_process') as {execFile: jest.Mock}

jest.mock('child_process', () => ({execFile: jest.fn()}))
jest.mock('@actions/core', () => ({info: jest.fn(), startGroup: jest.fn(), endGroup: jest.fn()}))

const HEAD = 'a'.repeat(40)
const OTHER_SHA = 'b'.repeat(40)
const GIT_DIR = '/tmp/runner/paths-filter-shadow.git'
const PAST_ANY_BUDGET_MS = 120000

type ExecFileArgs = [
  string,
  string[],
  {signal: AbortSignal},
  (error: Error | null, stdout: string, stderr: string) => void
]

const pullRequest = {number: 42, head: {sha: HEAD}} as PullRequest

function stubGit(...stdouts: string[]): void {
  for (const stdout of stdouts) {
    cp.execFile.mockImplementationOnce((...args: ExecFileArgs) => args[3](null, stdout, ''))
  }
}

function argvOf(call: number): string[] {
  return cp.execFile.mock.calls[call][1] as string[]
}

describe('shadow merge-commit comparison', () => {
  beforeEach(() => {
    process.env.RUNNER_TEMP = '/tmp/runner'
    process.env.GITHUB_SERVER_URL = 'https://github.com'
    process.env.GITHUB_REPOSITORY = 'PostHog/posthog'
    cp.execFile.mockReset()
  })

  // A git call that forgets the scratch dir runs against the job workspace, where a
  // --depth or --filter fetch drops the schema cache of every later step in the job.
  test('never runs git against the job workspace', async () => {
    stubGit('', '', HEAD, 'a.ts\0')

    const result = await compareWithMergeCommit([{filename: 'a.ts', status: ChangeStatus.Modified}], pullRequest)

    expect(result.verdict).toBe('match')
    expect(argvOf(0)).toContain(GIT_DIR)
    for (let call = 1; call < cp.execFile.mock.calls.length; call++) {
      expect(argvOf(call).slice(0, 2)).toEqual(['--git-dir', GIT_DIR])
    }
  })

  // Losing this guard scores a merge ref from an earlier push as this pull request's
  // changes, which fills the measurement with mismatches that mean nothing.
  test('refuses a stale merge ref instead of comparing against it', async () => {
    stubGit('', '', OTHER_SHA)

    const result = await compareWithMergeCommit([{filename: 'a.ts', status: ChangeStatus.Modified}], pullRequest)

    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toBe('stale-merge-ref')
  })

  // Losing --no-renames reports one path where the API path reports two, so every
  // rename reads as a mismatch.
  test('matches a rename that the API reported as two entries', async () => {
    stubGit('', '', HEAD, 'old.ts\0new.ts\0')

    const result = await compareWithMergeCommit(
      [
        {filename: 'new.ts', status: ChangeStatus.Added},
        {filename: 'old.ts', status: ChangeStatus.Deleted}
      ],
      pullRequest
    )

    expect(result.verdict).toBe('match')
    expect(cp.execFile.mock.calls.map(c => c[1])).toContainEqual(expect.arrayContaining(['--no-renames']))
  })

  // An exec with no handle on the child leaves the fetch running after the budget gives
  // up, and the action's process stays open until git exits.
  test('stops git when the budget expires', async () => {
    cp.execFile.mockImplementation(() => undefined)
    jest.useFakeTimers()

    const pending = compareWithMergeCommit([], pullRequest)
    await jest.advanceTimersByTimeAsync(PAST_ANY_BUDGET_MS)
    const result = await pending

    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toBe('budget-exceeded')
    const [, , options] = cp.execFile.mock.calls[0] as ExecFileArgs
    expect(options.signal.aborted).toBe(true)
    jest.useRealTimers()
  })
})

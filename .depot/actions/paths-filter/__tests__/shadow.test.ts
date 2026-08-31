import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus} from '../src/file'
import {Filter} from '../src/filter'
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

const filter = new Filter(`
backend:
  - 'posthog/**'
frontend:
  - 'frontend/**'
`)

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
    stubGit('', '', HEAD, 'M\0posthog/a.py\0')

    const result = await compareWithMergeCommit(
      filter,
      [{filename: 'posthog/a.py', status: ChangeStatus.Modified}],
      pullRequest
    )

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

    const result = await compareWithMergeCommit(
      filter,
      [{filename: 'posthog/a.py', status: ChangeStatus.Modified}],
      pullRequest
    )

    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toBe('stale-merge-ref')
  })

  // Losing --no-renames reports one path where the API path reports two, so every
  // rename reads as a mismatch.
  test('matches a rename that the API reported as two entries', async () => {
    stubGit('', '', HEAD, 'D\0posthog/old.py\0A\0posthog/new.py\0')

    const result = await compareWithMergeCommit(
      filter,
      [
        {filename: 'posthog/new.py', status: ChangeStatus.Added},
        {filename: 'posthog/old.py', status: ChangeStatus.Deleted}
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

    const pending = compareWithMergeCommit(filter, [], pullRequest)
    await jest.advanceTimersByTimeAsync(PAST_ANY_BUDGET_MS)
    const result = await pending

    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toBe('budget-exceeded')
    const [, , options] = cp.execFile.mock.calls[0] as ExecFileArgs
    expect(options.signal.aborted).toBe(true)
    jest.useRealTimers()
  })

  // A differing file list is only worth acting on where it flips a key, because the key
  // is what gates a job. Comparing the lists instead of the keys reports every dropped
  // path as consequential, which is the reading this field exists to replace.
  test.each([
    ['the dropped path is the only one holding a key', 'M\0frontend/b.ts\0', ['backend']],
    ['a surviving path holds the same key', 'M\0posthog/b.py\0M\0frontend/b.ts\0', []]
  ])('reports keys lost when %s', async (_case, diff, keysLost) => {
    stubGit('', '', HEAD, diff)

    const result = await compareWithMergeCommit(
      filter,
      [
        {filename: 'posthog/a.py', status: ChangeStatus.Modified},
        {filename: 'posthog/b.py', status: ChangeStatus.Modified},
        {filename: 'frontend/b.ts', status: ChangeStatus.Modified}
      ],
      pullRequest
    )

    expect(result.verdict).toBe('mismatch')
    expect(result.keysLost).toEqual(keysLost)
    expect(result.keysGained).toEqual([])
  })

  // --name-status emits a status field and a path field per entry. Reading them in the
  // wrong order turns every path into a status letter, and a rule scoped to a status
  // then answers on the wrong file.
  test('carries each file status through to a status-scoped rule', async () => {
    const scoped = new Filter(`
added_only:
  - added: 'posthog/**'
`)
    stubGit('', '', HEAD, 'A\0posthog/new.py\0D\0posthog/gone.py\0')

    const result = await compareWithMergeCommit(
      scoped,
      [
        {filename: 'posthog/new.py', status: ChangeStatus.Added},
        {filename: 'posthog/gone.py', status: ChangeStatus.Deleted}
      ],
      pullRequest
    )

    expect(result.verdict).toBe('match')
    expect(result.keysLost).toEqual([])
    expect(result.keysGained).toEqual([])
  })
})

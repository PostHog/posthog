import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus, File} from '../src/file'
import {Filter} from '../src/filter'
import {ShadowInput, compareWithMergeCommit} from '../src/shadow'

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

// The action matches the API list once in `run()` and hands the result to the shadow, so
// a test builds the same pairing here.
function input(withFilter: Filter, apiFiles: File[]): ShadowInput {
  return {
    filter: withFilter,
    apiFiles,
    apiResults: withFilter.match(apiFiles),
    apiRows: apiFiles.length,
    apiTruncated: false,
    pr: pullRequest
  }
}

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

  // A git call against the job workspace drops the schema cache of every later step.
  test('never runs git against the job workspace', async () => {
    stubGit('', '', HEAD, 'M\0posthog/a.py\0')

    const result = await compareWithMergeCommit(
      input(filter, [{filename: 'posthog/a.py', status: ChangeStatus.Modified}])
    )

    expect(result.verdict).toBe('match')
    expect(argvOf(0)).toContain(GIT_DIR)
    for (let call = 1; call < cp.execFile.mock.calls.length; call++) {
      expect(argvOf(call).slice(0, 2)).toEqual(['--git-dir', GIT_DIR])
    }
  })

  // Without this guard an earlier push's merge ref reads as this pull request's changes.
  test('refuses a stale merge ref instead of comparing against it', async () => {
    stubGit('', '', OTHER_SHA)

    const result = await compareWithMergeCommit(
      input(filter, [{filename: 'posthog/a.py', status: ChangeStatus.Modified}])
    )

    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toBe('stale-merge-ref')
  })

  // Without --no-renames every rename reads as a mismatch.
  test('matches a rename that the API reported as two entries', async () => {
    stubGit('', '', HEAD, 'D\0posthog/old.py\0A\0posthog/new.py\0')

    const result = await compareWithMergeCommit(
      input(filter, [
        {filename: 'posthog/new.py', status: ChangeStatus.Added},
        {filename: 'posthog/old.py', status: ChangeStatus.Deleted}
      ])
    )

    expect(result.verdict).toBe('match')
    expect(cp.execFile.mock.calls.map(c => c[1])).toContainEqual(expect.arrayContaining(['--no-renames']))
  })

  // Without a handle on the child, an abandoned fetch holds the action open until git exits.
  test('stops git when the budget expires', async () => {
    cp.execFile.mockImplementation(() => undefined)
    jest.useFakeTimers()

    const pending = compareWithMergeCommit(input(filter, []))
    await jest.advanceTimersByTimeAsync(PAST_ANY_BUDGET_MS)
    const result = await pending

    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toBe('budget-exceeded')
    const [, , options] = cp.execFile.mock.calls[0] as ExecFileArgs
    expect(options.signal.aborted).toBe(true)
    jest.useRealTimers()
  })

  // Comparing the file lists instead of the keys reports every dropped path as consequential.
  test.each([
    ['the dropped path is the only one holding a key', 'M\0frontend/b.ts\0', ['backend']],
    ['a surviving path holds the same key', 'M\0posthog/b.py\0M\0frontend/b.ts\0', []]
  ])('reports keys lost when %s', async (_case, diff, keysLost) => {
    stubGit('', '', HEAD, diff)

    const result = await compareWithMergeCommit(
      input(filter, [
        {filename: 'posthog/a.py', status: ChangeStatus.Modified},
        {filename: 'posthog/b.py', status: ChangeStatus.Modified},
        {filename: 'frontend/b.ts', status: ChangeStatus.Modified}
      ])
    )

    expect(result.verdict).toBe('mismatch')
    expect(result.keysLost).toEqual(keysLost)
    expect(result.keysGained).toEqual([])
  })

  // Reading the -z fields in the wrong order turns every path into a status letter.
  test('carries each file status through to a status-scoped rule', async () => {
    const scoped = new Filter(`
added_only:
  - added: 'posthog/**'
`)
    stubGit('', '', HEAD, 'A\0posthog/new.py\0D\0posthog/gone.py\0')

    const result = await compareWithMergeCommit(
      input(scoped, [
        {filename: 'posthog/new.py', status: ChangeStatus.Added},
        {filename: 'posthog/gone.py', status: ChangeStatus.Deleted}
      ])
    )

    expect(result.verdict).toBe('match')
    expect(result.keysLost).toEqual([])
    expect(result.keysGained).toEqual([])
  })
})

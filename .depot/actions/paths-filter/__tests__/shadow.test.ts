import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus, File} from '../src/file'
import {compareWithMergeCommit} from '../src/shadow'

const exec = jest.requireMock('@actions/exec') as {getExecOutput: jest.Mock}

jest.mock('@actions/exec', () => ({getExecOutput: jest.fn()}))
jest.mock('@actions/core', () => ({
  info: jest.fn(),
  warning: jest.fn(),
  startGroup: jest.fn(),
  endGroup: jest.fn()
}))

const HEAD = 'a'.repeat(40)
const pr = {number: 42, head: {sha: HEAD}} as PullRequest

function apiFiles(...names: string[]): File[] {
  return names.map(filename => ({filename, status: ChangeStatus.Modified}))
}

// Each entry answers one call, in the order shadow.ts makes them:
// init, fetch, rev-parse ^2, diff.
function gitResponses(...responses: {exitCode?: number; stdout?: string}[]): void {
  exec.getExecOutput.mockReset()
  for (const r of responses) {
    exec.getExecOutput.mockResolvedValueOnce({exitCode: r.exitCode ?? 0, stdout: r.stdout ?? '', stderr: ''})
  }
}

const INIT_OK = {}
const FETCH_OK = {}
const HEAD_OK = {stdout: HEAD}

function argvFor(call: number): string[] {
  return exec.getExecOutput.mock.calls[call][1] as string[]
}

describe('shadow merge-commit comparison', () => {
  beforeEach(() => {
    process.env.RUNNER_TEMP = '/tmp/runner'
    process.env.GITHUB_SERVER_URL = 'https://github.com'
    process.env.GITHUB_REPOSITORY = 'PostHog/posthog'
  })

  it('reports a match when both sides list the same files', async () => {
    gitResponses(INIT_OK, FETCH_OK, HEAD_OK, {stdout: 'a.ts\0b.ts\0'})
    const result = await compareWithMergeCommit(apiFiles('a.ts', 'b.ts'), pr)
    expect(result.verdict).toBe('match')
  })

  it('reports a mismatch and names the files each side is missing', async () => {
    gitResponses(INIT_OK, FETCH_OK, HEAD_OK, {stdout: 'a.ts\0c.ts\0'})
    const result = await compareWithMergeCommit(apiFiles('a.ts', 'b.ts'), pr)
    expect(result.verdict).toBe('mismatch')
    expect(result.onlyInApi).toEqual(['b.ts'])
    expect(result.onlyInGit).toEqual(['c.ts'])
  })

  // A --depth or --filter fetch rewrites the shallow boundary and promisor config of
  // whichever repository it runs in. Steps after this action read history from the
  // workspace checkout, so every call has to name the scratch git dir.
  it('never runs git against the job workspace', async () => {
    gitResponses(INIT_OK, FETCH_OK, HEAD_OK, {stdout: 'a.ts\0'})
    await compareWithMergeCommit(apiFiles('a.ts'), pr)

    expect(argvFor(0)).toEqual(['init', '--bare', '--quiet', '/tmp/runner/paths-filter-shadow.git'])
    for (let call = 1; call < exec.getExecOutput.mock.calls.length; call++) {
      expect(argvFor(call).slice(0, 2)).toEqual(['--git-dir', '/tmp/runner/paths-filter-shadow.git'])
    }
    expect(argvFor(1)).toContain('--depth=2')
    expect(argvFor(1)).toContain('--filter=blob:none')
  })

  // git quotes a path containing a newline or a non-ASCII byte unless output is
  // NUL-delimited, and a quoted path would read as a file neither side has.
  it('reads NUL-delimited diff output', async () => {
    gitResponses(INIT_OK, FETCH_OK, HEAD_OK, {stdout: 'a.ts\0dir/b c.ts\0'})
    const result = await compareWithMergeCommit(apiFiles('a.ts', 'dir/b c.ts'), pr)
    expect(result.verdict).toBe('match')
    expect(argvFor(3)).toContain('-z')
  })

  // A merge ref GitHub has not recomputed since the last push describes an older
  // head. Reading it would silently attribute the wrong changes to this pull request.
  it('refuses a stale merge ref instead of comparing against it', async () => {
    gitResponses(INIT_OK, FETCH_OK, {stdout: 'c'.repeat(40)}, {stdout: 'a.ts\0'})
    const result = await compareWithMergeCommit(apiFiles('a.ts'), pr)
    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toContain('stale')
  })

  it('reports unavailable when the merge ref has no second parent', async () => {
    gitResponses(INIT_OK, FETCH_OK, {exitCode: 128})
    const result = await compareWithMergeCommit(apiFiles('a.ts'), pr)
    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toContain('second parent')
  })

  it('reports unavailable when the merge ref cannot be fetched', async () => {
    gitResponses(INIT_OK, {exitCode: 128})
    const result = await compareWithMergeCommit(apiFiles('a.ts'), pr)
    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toContain('merge ref')
  })

  // The API path turns a rename into a delete of the old name plus an add of the new
  // one, and `git diff --no-renames` emits the same pair.
  it('matches a rename that the API reported as two entries', async () => {
    gitResponses(INIT_OK, FETCH_OK, HEAD_OK, {stdout: 'new.ts\0old.ts\0'})
    const result = await compareWithMergeCommit(apiFiles('new.ts', 'old.ts'), pr)
    expect(result.verdict).toBe('match')
    expect(argvFor(3)).toContain('--no-renames')
  })
})

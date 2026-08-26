import {PullRequest} from '@octokit/webhooks-types'

import {ChangeStatus, File} from '../src/file'
import {compareWithMergeCommit} from '../src/shadow'

const exec = jest.requireMock('@actions/exec') as {getExecOutput: jest.Mock}

jest.mock('@actions/exec', () => ({getExecOutput: jest.fn()}))
jest.mock('@actions/core', () => ({
  info: jest.fn(),
  warning: jest.fn(),
  startGroup: jest.fn(),
  endGroup: jest.fn(),
  setOutput: jest.fn()
}))

const HEAD = 'a'.repeat(40)
const pr = {number: 42, head: {sha: HEAD}} as PullRequest

function apiFiles(...names: string[]): File[] {
  return names.map(filename => ({filename, status: ChangeStatus.Modified}))
}

// Each entry answers one `git` call, in the order shadow.ts makes them:
// fetch, rev-list --parents, rev-parse ^2, diff.
function gitResponses(...responses: {exitCode?: number; stdout?: string}[]): void {
  exec.getExecOutput.mockReset()
  for (const r of responses) {
    exec.getExecOutput.mockResolvedValueOnce({exitCode: r.exitCode ?? 0, stdout: r.stdout ?? '', stderr: ''})
  }
}

describe('shadow merge-commit comparison', () => {
  it('reports a match when both sides list the same files', async () => {
    gitResponses({}, {stdout: `m ${'b'.repeat(40)} ${HEAD}`}, {stdout: HEAD}, {stdout: 'a.ts\nb.ts\n'})
    const result = await compareWithMergeCommit(apiFiles('a.ts', 'b.ts'), pr)
    expect(result.verdict).toBe('match')
  })

  it('reports a mismatch and names the files each side is missing', async () => {
    gitResponses({}, {stdout: `m ${'b'.repeat(40)} ${HEAD}`}, {stdout: HEAD}, {stdout: 'a.ts\nc.ts\n'})
    const result = await compareWithMergeCommit(apiFiles('a.ts', 'b.ts'), pr)
    expect(result.verdict).toBe('mismatch')
    expect(result.onlyInApi).toEqual(['b.ts'])
    expect(result.onlyInGit).toEqual(['c.ts'])
  })

  // A merge ref GitHub has not recomputed since the last push describes an older
  // head. Reading it would silently attribute the wrong changes to this PR.
  it('refuses a stale merge ref instead of comparing against it', async () => {
    gitResponses({}, {stdout: `m ${'b'.repeat(40)} ${'c'.repeat(40)}`}, {stdout: 'c'.repeat(40)}, {stdout: 'a.ts\n'})
    const result = await compareWithMergeCommit(apiFiles('a.ts'), pr)
    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toContain('stale')
  })

  it('reports unavailable when the checkout has no second parent', async () => {
    gitResponses({}, {stdout: `m ${'b'.repeat(40)}`})
    const result = await compareWithMergeCommit(apiFiles('a.ts'), pr)
    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toContain('second parent')
  })

  it('reports unavailable when the merge ref cannot be fetched', async () => {
    gitResponses({exitCode: 1})
    const result = await compareWithMergeCommit(apiFiles('a.ts'), pr)
    expect(result.verdict).toBe('unavailable')
    expect(result.reason).toContain('merge ref')
  })

  // The API path turns a rename into a delete of the old name plus an add of the
  // new one, and `git diff --no-renames` emits the same pair.
  it('matches a rename that the API reported as two entries', async () => {
    gitResponses({}, {stdout: `m ${'b'.repeat(40)} ${HEAD}`}, {stdout: HEAD}, {stdout: 'new.ts\nold.ts\n'})
    const result = await compareWithMergeCommit(apiFiles('new.ts', 'old.ts'), pr)
    expect(result.verdict).toBe('match')
  })
})

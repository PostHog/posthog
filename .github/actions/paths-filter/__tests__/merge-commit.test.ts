import {getExecOutput} from '@actions/exec'

import * as git from '../src/git'
import {ChangeStatus, normalizeApiFile} from '../src/file'

jest.mock('@actions/exec')

const execMock = getExecOutput as jest.MockedFunction<typeof getExecOutput>

const PR_HEAD = '3cfe853d32de4cbd9b4b06c640778097da951b09'
const BASE = '50496ac6f428bdb02dc99b6cba99d9ae076ed5d2'
const MERGE = '5c56da6784e6ea7ea495fedf810539678732dc28'

function execResult(stdout: string, exitCode = 0): ReturnType<typeof getExecOutput> {
  return Promise.resolve({exitCode, stdout, stderr: ''})
}

// `git rev-list --parents -n 1 HEAD` prints the commit followed by its parents.
function revList(...parents: string[]): string {
  return [MERGE, ...parents].join(' ') + '\n'
}

// `git diff -z` terminates every status and every path with NUL.
const NUL = '\u0000'

function nameStatus(...entries: [string, string][]): string {
  return entries.map(([status, path]) => `${status}${NUL}${path}${NUL}`).join('')
}

describe('change detection from the checked-out merge commit', () => {
  test('diffs HEAD^1..HEAD when HEAD is the merge commit for the PR head', async () => {
    execMock
      .mockReturnValueOnce(execResult(revList(BASE, PR_HEAD)))
      .mockReturnValueOnce(execResult(nameStatus(['A', 'added.ts'], ['M', 'changed.ts'], ['D', 'gone.ts'])))

    const files = await git.getChangesFromMergeCommit(PR_HEAD)

    expect(files).toEqual([
      {filename: 'added.ts', status: ChangeStatus.Added},
      {filename: 'changed.ts', status: ChangeStatus.Modified},
      {filename: 'gone.ts', status: ChangeStatus.Deleted}
    ])
    expect(execMock).toHaveBeenLastCalledWith('git', ['diff', '--no-renames', '--name-status', '-z', 'HEAD^1', 'HEAD'])
  })

  test.each([
    ['HEAD^2 is not the PR head', revList(BASE, 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')],
    ['HEAD has a single parent', revList(BASE)],
    ['a shallow checkout hides the parents', revList()]
  ])('returns null and runs no diff when %s', async (_name, output) => {
    execMock.mockReturnValueOnce(execResult(output))

    expect(await git.getChangesFromMergeCommit(PR_HEAD)).toBeNull()
    expect(execMock).toHaveBeenCalledTimes(1)
  })

  test('a rename reads the same from the merge commit and from the API', async () => {
    execMock
      .mockReturnValueOnce(execResult(revList(BASE, PR_HEAD)))
      .mockReturnValueOnce(execResult(nameStatus(['A', 'new/path.ts'], ['D', 'old/path.ts'])))

    const fromGit = await git.getChangesFromMergeCommit(PR_HEAD)
    const fromApi = normalizeApiFile({
      filename: 'new/path.ts',
      status: 'renamed',
      previous_filename: 'old/path.ts'
    })

    expect(fromGit).toEqual([
      {filename: 'new/path.ts', status: ChangeStatus.Added},
      {filename: 'old/path.ts', status: ChangeStatus.Deleted}
    ])
    expect(fromApi).toEqual(fromGit)
  })

  test.each([
    ['added', ChangeStatus.Added],
    ['modified', ChangeStatus.Modified],
    ['removed', ChangeStatus.Deleted]
  ])('maps the API status %s onto the git status', (status, expected) => {
    expect(normalizeApiFile({filename: 'a.ts', status})).toEqual([{filename: 'a.ts', status: expected}])
  })
})

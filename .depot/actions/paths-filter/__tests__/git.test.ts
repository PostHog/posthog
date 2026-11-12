import {execFileSync} from 'child_process'
import {mkdtempSync, rmSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import {join} from 'path'

import * as git from '../src/git'
import {ChangeStatus} from '../src/file'

describe('parsing output of the git diff command', () => {
  test('parseGitDiffOutput returns files with correct change status', async () => {
    const files = git.parseGitDiffOutput(
      'A\u0000LICENSE\u0000' + 'M\u0000src/index.ts\u0000' + 'D\u0000src/main.ts\u0000'
    )
    expect(files.length).toBe(3)
    expect(files[0].filename).toBe('LICENSE')
    expect(files[0].status).toBe(ChangeStatus.Added)
    expect(files[1].filename).toBe('src/index.ts')
    expect(files[1].status).toBe(ChangeStatus.Modified)
    expect(files[2].filename).toBe('src/main.ts')
    expect(files[2].status).toBe(ChangeStatus.Deleted)
  })
})

describe('git utility function tests (those not invoking git)', () => {
  test('Trims "refs/" and "heads/" from ref', () => {
    expect(git.getShortName('refs/heads/master')).toBe('master')
    expect(git.getShortName('heads/master')).toBe('heads/master')
    expect(git.getShortName('master')).toBe('master')

    expect(git.getShortName('refs/tags/v1')).toBe('v1')
    expect(git.getShortName('tags/v1')).toBe('tags/v1')
    expect(git.getShortName('v1')).toBe('v1')
  })

  test('isGitSha(ref) returns true only for 40 characters of a-z and 0-9', () => {
    expect(git.isGitSha('8b399ed1681b9efd6b1e048ca1c5cba47edf3855')).toBeTruthy()
    expect(git.isGitSha('This_is_very_long_name_for_a_branch_1111')).toBeFalsy()
    expect(git.isGitSha('master')).toBeFalsy()
  })
})

describe('git filename logging', () => {
  const modes = ['last commit', 'two refs', 'working tree', 'merge base', 'all files'] as const
  const filenames = ['ordinary.txt', 'line\n::notice::filename\n.txt', 'return\r::notice::filename\r.txt']

  test.each(modes)('%s preserves filenames without writing them as log commands', async mode => {
    const directory = mkdtempSync(join(tmpdir(), 'paths-filter-git-'))
    const cwd = process.cwd()
    const gitCommand = (...args: string[]): string =>
      execFileSync('git', args, {cwd: directory, encoding: 'utf8'}).trim()
    const commitTree = (parent?: string): string =>
      execFileSync('git', ['commit-tree', gitCommand('write-tree'), ...(parent ? ['-p', parent] : [])], {
        cwd: directory,
        encoding: 'utf8',
        input: 'fixture\n',
        env: {
          ...process.env,
          GIT_AUTHOR_NAME: 'Test',
          GIT_AUTHOR_EMAIL: 'test@example.com',
          GIT_COMMITTER_NAME: 'Test',
          GIT_COMMITTER_EMAIL: 'test@example.com'
        }
      }).trim()
    let log = ''
    let capture: jest.SpyInstance | undefined
    try {
      gitCommand('init', '-q', '--initial-branch=master')
      const base = commitTree()
      for (const filename of filenames) writeFileSync(join(directory, filename), 'before')
      gitCommand('add', '.')
      const head = commitTree(base)
      gitCommand('update-ref', 'refs/heads/master', head)
      for (const filename of filenames) writeFileSync(join(directory, filename), 'after')
      process.chdir(directory)
      capture = jest.spyOn(process.stdout, 'write').mockImplementation(chunk => {
        log += String(chunk)
        return true
      })
      const files =
        mode === 'last commit'
          ? await git.getChangesInLastCommit()
          : mode === 'two refs'
          ? await git.getChanges(base, head)
          : mode === 'working tree'
          ? await git.getChangesOnHead()
          : mode === 'merge base'
          ? await git.getChangesSinceMergeBase(base, head, 10)
          : await git.listAllFilesAsAdded()
      expect(files.map(file => file.filename).sort()).toEqual([...filenames].sort())
      expect(log).not.toMatch(/(?:^|[\r\n])::notice::filename/)
    } finally {
      capture?.mockRestore()
      process.chdir(cwd)
      rmSync(directory, {recursive: true, force: true})
    }
  })
})

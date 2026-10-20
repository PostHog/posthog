import {execFileSync} from 'child_process'
import {mkdtempSync, mkdirSync, readFileSync, renameSync, rmSync, symlinkSync, unlinkSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {parseGitDiffOutput} from '../../paths-filter/src/git'
import {ChangeStatus, Filter, intervalFiles} from '../src/shared-image'

let repo: string
const git = (...args: string[]): string => execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', ...args], {cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}).trim()
const put = (name: string, contents = name): void => {
  mkdirSync(path.dirname(path.join(repo, name)), {recursive: true})
  writeFileSync(path.join(repo, name), contents)
}
const commit = (name: string): string => {
  git('add', '-A')
  git('commit', '-m', name)
  return git('rev-parse', 'HEAD')
}
const options = (): {cwd: string; timeoutMs: number; maxBuffer: number} => ({cwd: repo, timeoutMs: 10000, maxBuffer: 1024 * 1024})

beforeEach(() => {
  repo = mkdtempSync(path.join(tmpdir(), 'shared-image-history-'))
  git('init', '-b', 'main')
  git('config', 'user.name', 'Fixture')
  git('config', 'user.email', 'fixture@example.invalid')
})
afterEach(() => rmSync(repo, {recursive: true, force: true}))

describe('executing checkout first-parent interval', () => {
  test('batched entries equal each delta, including merges, renames, typechanges, distinct statuses and unusual paths', () => {
    put('worker/run.py', 'base')
    put('worker/rename.py')
    put('worker/typechange.py')
    const base = commit('base')
    git('checkout', '-b', 'feature')
    put('worker/merged.py')
    const secondParent = commit('feature')
    git('checkout', 'main')
    put('other/main.txt')
    commit('main')
    git('merge', '--no-ff', 'feature', '-m', 'merge')
    renameSync(path.join(repo, 'worker/rename.py'), path.join(repo, 'other/renamed.py'))
    unlinkSync(path.join(repo, 'worker/typechange.py'))
    symlinkSync('run.py', path.join(repo, 'worker/typechange.py'))
    for (const file of ['space name.py', 'tab\tname.py', 'newline\nname.py', '.dot.py', 'tests/test.py']) put(`worker/${file}`)
    commit('rename and unusual paths')
    put('worker/temporary.py')
    commit('add')
    unlinkSync(path.join(repo, 'worker/temporary.py'))
    const head = commit('delete')
    const files = intervalFiles(base, head, options())
    const individual = git('rev-list', '--first-parent', `${base}..${head}`).split('\n').flatMap(sha => {
      const output = execFileSync('git', ['diff', '--no-renames', '--name-status', '-z', `${sha}^1`, sha], {cwd: repo, encoding: 'utf8'})
      return parseGitDiffOutput(output).map(file => file.status === undefined ? {...file, status: ChangeStatus.Modified} : file)
    })
    expect(parseGitDiffOutput('T\0worker/typechange.py\0')[0].status).toBeUndefined()
    expect(files).toEqual(individual)
    for (const entry of [
      {filename: 'worker/merged.py', status: ChangeStatus.Added},
      {filename: 'worker/typechange.py', status: ChangeStatus.Modified},
      {filename: 'worker/rename.py', status: ChangeStatus.Deleted},
      {filename: 'other/renamed.py', status: ChangeStatus.Added},
      {filename: 'worker/temporary.py', status: ChangeStatus.Added},
      {filename: 'worker/temporary.py', status: ChangeStatus.Deleted},
      {filename: 'worker/newline\nname.py', status: ChangeStatus.Added},
      {filename: 'worker/space name.py', status: ChangeStatus.Added},
      {filename: 'worker/tab\tname.py', status: ChangeStatus.Added}
    ]) expect(files).toContainEqual(entry)
    const filter = new Filter(yaml.dump({worker: ['worker/**', '!worker/tests/**']}))
    expect(filter.match(files).worker).toEqual(filter.match(individual).worker)
    expect(filter.match(files).worker.some(file => file.filename.includes('\n'))).toBe(false)
    expect(() => intervalFiles(secondParent, head, options())).toThrow(/first-parent/)
  })

  test('a failed or skipped relevant build remains eligible on a later unrelated successful revision', () => {
    put('worker/run.py', 'base')
    const base = commit('base')
    put('worker/run.py', 'changed')
    const missed = commit('relevant build did not publish')
    put('other/unrelated.txt')
    const head = commit('successful build')
    const filter = new Filter('worker: ["worker/**"]')
    expect(filter.match(intervalFiles(base, head, options())).worker.length).toBe(1)
    expect(filter.match(intervalFiles(missed, head, options())).worker).toEqual([])
  })

  test('history membership fits an interval budget smaller than the complete first-parent history', () => {
    for (let index = 0; index < 4; index++) {
      put('other.txt', `${index}`)
      commit('earlier history')
    }
    const base = git('rev-parse', 'HEAD')
    put('worker/run.py')
    const head = commit('relevant interval')
    expect(Buffer.byteLength(git('rev-list', '--first-parent', head))).toBeGreaterThan(100)
    expect(intervalFiles(base, head, {...options(), maxBuffer: 100})).toEqual([
      {filename: 'worker/run.py', status: ChangeStatus.Added}
    ])
  })

  test('missing history, wrong checkout and exhausted budgets fail explicitly', () => {
    put('worker/run.py')
    const base = commit('base')
    put('worker/run.py', 'changed')
    const head = commit('head')
    expect(() => intervalFiles('f'.repeat(40), head, options())).toThrow()
    expect(() => intervalFiles(base, base, options())).toThrow(/checkout/)
    expect(() => intervalFiles(base, head, {...options(), timeoutMs: 0})).toThrow(/timed out/)
    expect(() => intervalFiles(base, head, {...options(), maxBuffer: 1})).toThrow()
    expect(intervalFiles(head, head, options())).toEqual([])
    expect(readFileSync(path.join(repo, 'worker/run.py'), 'utf8')).toBe('changed')
    writeFileSync(path.join(repo, '.git/shallow'), `${head}\n`)
    expect(() => intervalFiles(base, head, options())).toThrow(/Complete executing source history/)
    unlinkSync(path.join(repo, '.git/shallow'))
    const tree = git('rev-parse', `${head}^{tree}`)
    const treePath = path.join(repo, '.git/objects', tree.slice(0, 2), tree.slice(2))
    const object = readFileSync(treePath)
    unlinkSync(treePath)
    try {
      expect(() => intervalFiles(base, head, options())).toThrow()
    } finally {
      writeFileSync(treePath, object)
    }
  })
})

import {execFileSync} from 'child_process'
import {mkdtempSync, mkdirSync, readFileSync, renameSync, rmSync, symlinkSync, unlinkSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {parseGitDiffOutput} from '../../paths-filter/src/git'
import {ChangeStatus, Filter, GitRunner, intervalFiles, POLICY_PATH} from '../src/shared-image'
import {SourceHistory} from '../src/shared-image-history'
import * as commands from '../src/shared-image-command'

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
const options = (overrides: {timeoutMs?: number; maxBuffer?: number} = {}): GitRunner => {
  const history = new SourceHistory(repo, {fetchMs: 30000, comparisonMs: 30000, maxBuffer: overrides.maxBuffer ?? 1024 * 1024, retryDelaysMs: [0, 0]})
  const deadline = Date.now() + (overrides.timeoutMs ?? 30000)
  return args => history.git(args, deadline)
}

beforeEach(() => {
  repo = mkdtempSync(path.join(tmpdir(), 'shared-image-history-'))
  git('init', '-b', 'main')
  git('config', 'user.name', 'Fixture')
  git('config', 'user.email', 'fixture@example.invalid')
})
afterEach(() => rmSync(repo, {recursive: true, force: true}))

describe('executing checkout first-parent interval', () => {
  test('batched entries equal each delta, including merges, renames, typechanges, distinct statuses and unusual paths', async () => {
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
    const files = await intervalFiles(base, head, options())
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
    await expect(intervalFiles(secondParent, head, options())).rejects.toThrow(/first-parent/)
  })

  test('a failed or skipped relevant build remains eligible on a later unrelated successful revision', async () => {
    put('worker/run.py', 'base')
    const base = commit('base')
    put('worker/run.py', 'changed')
    const missed = commit('relevant build did not publish')
    put('other/unrelated.txt')
    const head = commit('successful build')
    const filter = new Filter('worker: ["worker/**"]')
    expect(filter.match(await intervalFiles(base, head, options())).worker.length).toBe(1)
    expect(filter.match(await intervalFiles(missed, head, options())).worker).toEqual([])
  })

  test('history membership fits an interval budget smaller than the complete first-parent history', async () => {
    for (let index = 0; index < 4; index++) {
      put('other.txt', `${index}`)
      commit('earlier history')
    }
    const base = git('rev-parse', 'HEAD')
    put('worker/run.py')
    const head = commit('relevant interval')
    expect(Buffer.byteLength(git('rev-list', '--first-parent', head))).toBeGreaterThan(100)
    expect(await intervalFiles(base, head, options({maxBuffer: 100}))).toEqual([
      {filename: 'worker/run.py', status: ChangeStatus.Added}
    ])
  })

  test.each(['short', 'long'])('tree discovery streams %s revision lists through stdin', async size => {
    put('worker/run.py', 'base')
    const base = commit('base')
    put('worker/run.py', 'changed')
    const head = commit('head')
    const argumentLimit = Number(execFileSync('getconf', ['ARG_MAX'], {encoding: 'utf8'}).trim())
    const count = size === 'short' ? 2 : Math.ceil(argumentLimit / (head.length + 1)) + 1
    const revisions = Array.from({length: count}, (_, index) => index % 2 ? head : base)
    const input = revisions.join('\n') + '\n'
    if (size === 'long') expect(Buffer.byteLength(input)).toBeGreaterThan(argumentLimit)
    const history = new SourceHistory(repo, {fetchMs: 30000, comparisonMs: 30000, maxBuffer: 4 * 1024 * 1024, retryDelaysMs: [0, 0]})
    const runner = jest.spyOn(history, 'git')
    try {
      await expect(history['trees'](revisions, Date.now() + 30000)).resolves.toBeUndefined()
      const discovery = runner.mock.calls.find(([args]) => args.includes('--format=%T'))!
      expect(discovery[0]).toEqual(['rev-list', '--no-walk', '--no-commit-header', '--format=%T', '--stdin'])
      expect(discovery[0].some(argument => revisions.includes(argument))).toBe(false)
      expect(discovery[2]).toBe(input)
      process.stdout.write(JSON.stringify({treeDiscovery: size, argumentLimit, revisions: count, inputBytes: Buffer.byteLength(input)}) + '\n')
    } finally { runner.mockRestore() }
  })

  test('missing history, wrong checkout and exhausted budgets fail explicitly', async () => {
    put('worker/run.py')
    const base = commit('base')
    put('worker/run.py', 'changed')
    const head = commit('head')
    await expect(intervalFiles('f'.repeat(40), head, options())).rejects.toThrow()
    await expect(intervalFiles(base, base, options())).rejects.toThrow(/checkout/)
    await expect(intervalFiles(base, head, options({timeoutMs: 0}))).rejects.toThrow(/budget exhausted/)
    await expect(intervalFiles(base, head, options({maxBuffer: 1}))).rejects.toThrow()
    expect(await intervalFiles(head, head, options())).toEqual([])
    expect(readFileSync(path.join(repo, 'worker/run.py'), 'utf8')).toBe('changed')
    writeFileSync(path.join(repo, '.git/shallow'), `${head}\n`)
    await expect(intervalFiles(base, head, options())).rejects.toThrow(/Complete executing source history/)
    unlinkSync(path.join(repo, '.git/shallow'))
    const tree = git('rev-parse', `${head}^{tree}`)
    const treePath = path.join(repo, '.git/objects', tree.slice(0, 2), tree.slice(2))
    const object = readFileSync(treePath)
    unlinkSync(treePath)
    try {
      await expect(intervalFiles(base, head, options())).rejects.toThrow()
    } finally {
      writeFileSync(treePath, object)
    }
  })

  test.each(['root', 'subtree'])('missing %s trees require a complete checkout without fetching', async missing => {
    const history = new SourceHistory(repo, {fetchMs: 30000, comparisonMs: 30000, maxBuffer: 1024, retryDelaysMs: [0, 0]})
    const tree = 'b'.repeat(40)
    const runner = jest.spyOn(history, 'git').mockImplementation(async args => {
      if (args[0] === 'cat-file') return missing === 'root' ? `${tree} missing\n` : `${tree} tree\n`
      if (args.includes('--format=%T')) return tree + '\n'
      if (args.includes('--objects')) return '?' + 'c'.repeat(40) + '\n'
      throw new Error('Unexpected Git command')
    })
    await expect(history.policyAt('a'.repeat(40))).rejects.toThrow('The checkout must provide full history with trees')
    expect(runner.mock.calls.some(([args]) => args[0] === 'fetch')).toBe(false)
  })

  test.each(['fetch', 'action'])('fetch retries stop when the %s deadline cannot fit the next wait', async budget => {
    jest.useFakeTimers()
    const deadline = Date.now() + 7999
    const history = new SourceHistory(repo, {fetchMs: budget === 'fetch' ? 7999 : 30000, comparisonMs: 30000, maxBuffer: 1024, retryDelaysMs: [5000, 15000]}, budget === 'action' ? deadline : Infinity)
    const tree = 'b'.repeat(40)
    const runner = jest.spyOn(commands, 'command').mockImplementation(async (_executable, args) => {
      if (args[0] === 'fetch') throw new Error('transient fetch failure')
      if (args[0] === 'rev-list') return `${tree}\n`
      if (args[0] === 'cat-file') {
        if (args[1] === '-e') throw new Error('policy blob is missing')
        return `${tree} tree\n`
      }
      if (args[0] === 'ls-tree') return `100644 blob ${'c'.repeat(40)}\t${POLICY_PATH}\n`
      throw new Error('Unexpected Git command')
    })
    try {
      const result = expect(history.policyAt('a'.repeat(40)))
        .rejects.toThrow(/^attempt 1 of 3: Error: transient fetch failure; retries skipped: fetch budget exhausted$/)
      await jest.runAllTimersAsync()
      await result
      expect(runner.mock.calls.filter(([_executable, args]) => args[0] === 'fetch')).toHaveLength(1)
    } finally {
      runner.mockRestore()
      jest.useRealTimers()
    }
  })
})

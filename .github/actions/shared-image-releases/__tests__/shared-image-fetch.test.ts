import {execFileSync} from 'child_process'
import {chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import {publishChannels, PublisherOptions} from '../src/shared-image-publisher'
import {Filter, POLICY_PATH, policyDigest} from '../src/shared-image'
import {ReleaseRegistry} from '../src/shared-image-registry'
import * as commands from '../src/shared-image-command'
import {SourceHistory} from '../src/shared-image-history'

jest.unmock('../src/shared-image-command')
let scratch: string
const git = (cwd: string, ...args: string[]): string => execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', ...args], {
  cwd, env: {...process.env, GIT_NO_LAZY_FETCH: '1'}, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
}).trim()
beforeEach(() => { scratch = mkdtempSync(path.join(tmpdir(), 'shared-image-fetch-')) })
afterEach(() => { jest.restoreAllMocks(); rmSync(scratch, {recursive: true, force: true}) })

describe('publisher bounded tree fetching with the real command runner', () => {
  test.each(['available', 'slow policy fetch', 'missing subtrees', 'missing', 'probe failure', 'fetch and probe failure'])('bounded tree fetch: %s', async mode => {
    const available = mode === 'available' || mode === 'slow policy fetch' || mode === 'missing subtrees' || mode === 'probe failure'
    const source = path.join(scratch, 'source')
    const cwd = path.join(scratch, 'executing')
    const origin = path.join(scratch, 'origin.git')
    mkdirSync(source)
    git(source, 'init', '-b', 'main'); git(source, 'config', 'user.name', 'Fixture'); git(source, 'config', 'user.email', 'fixture@example.invalid')
    git(scratch, 'init', '--bare', '-b', 'main', origin)
    git(scratch, '--git-dir', origin, 'config', 'uploadpack.allowFilter', 'true')
    git(scratch, '--git-dir', origin, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
    git(source, 'remote', 'add', 'origin', `file://${origin}`)
    const put = (name: string, value: string): void => {
      const file = path.join(source, name); mkdirSync(path.dirname(file), {recursive: true}); writeFileSync(file, value)
    }
    const commit = (): string => { git(source, 'add', '-A'); git(source, 'commit', '-m', 'fixture'); return git(source, 'rev-parse', 'HEAD') }
    const alias = (revision: string): string => `r${git(cwd, 'rev-list', '--first-parent', '--count', revision).padStart(12, '0')}-${revision.slice(0, 6)}`
    put(POLICY_PATH, JSON.stringify({version: 1, filters: {worker: ['worker/**']}, images: {'posthog-cloud': {channels: {worker: {repository: 'workers/worker', filter: 'worker'}}}}}))
    put('worker/run.py', 'base'); const base = commit()
    git(source, 'push', 'origin', 'main')
    put('worker/run.py', 'unpublished'); const relevant = commit()
    put(POLICY_PATH, JSON.stringify({version: 1, filters: {worker: ['new-worker/**']}, images: {'posthog-cloud': {channels: {worker: {repository: 'workers/worker', filter: 'worker'}}}}})); commit()
    put('unrelated.txt', 'later successful build'); const revision = commit()
    git(source, 'push', 'origin', 'main')
    git(scratch, 'clone', '--no-local', '--depth', '1', `file://${origin}`, cwd)
    expect(git(cwd, 'rev-parse', '--is-shallow-repository')).toBe('true')
    git(cwd, 'fetch', '--unshallow', '--filter=tree:0', 'origin')
    expect(git(cwd, 'rev-parse', '--is-shallow-repository')).toBe('false')
    expect(git(cwd, 'config', 'remote.origin.promisor')).toBe('true')
    expect(git(cwd, 'config', 'remote.origin.partialclonefilter')).toBe('tree:0')
    const tree = git(source, 'rev-parse', `${relevant}^{tree}`)
    const policyBlob = git(source, 'rev-parse', `${base}:${POLICY_PATH}`)
    expect(() => git(cwd, 'cat-file', '-e', tree)).toThrow()
    expect(() => git(cwd, 'cat-file', '-e', policyBlob)).toThrow()
    if (mode === 'missing subtrees') {
      const roots = git(source, 'rev-list', '--all', '--no-commit-header', '--format=%T').split('\n')
      for (const root of roots) {
        const raw = execFileSync('git', ['cat-file', 'tree', root], {cwd: source})
        execFileSync('git', ['hash-object', '-w', '-t', 'tree', '--stdin'], {cwd, input: raw})
      }
      expect(() => git(cwd, 'cat-file', '-e', tree)).not.toThrow()
      expect(() => git(cwd, 'cat-file', '-e', git(source, 'rev-parse', `${base}:.github`))).toThrow()
    }
    if (!available) {
      const incomplete = path.join(scratch, 'incomplete.git')
      git(scratch, 'init', '--bare', '-b', 'main', incomplete)
      git(source, 'push', incomplete, `${base}:refs/heads/main`)
      git(cwd, 'remote', 'set-url', 'origin', `file://${incomplete}`)
    }
    const regctl = path.join(scratch, 'regctl')
    writeFileSync(regctl, '#!/bin/sh\nexit 1\n'); chmodSync(regctl, 0o755)
    const destination = {repository: 'workers/worker', registry: '123456789012.dkr.ecr.us-east-1.amazonaws.com'}
    const published = new Set<string>()
    jest.spyOn(ReleaseRegistry.prototype, 'list').mockResolvedValue({tags: new Set([alias(base)]), nonempty: true})
    jest.spyOn(ReleaseRegistry.prototype, 'read').mockResolvedValue({digest: 'sha256:' + 'a'.repeat(64), outcome: 'integrity-mismatch'})
    jest.spyOn(ReleaseRegistry.prototype, 'identity').mockImplementation(async (_registry, repository, digest) => ({
      revision: repository === destination.repository ? base : revision, digest
    }))
    jest.spyOn(ReleaseRegistry.prototype, 'publish').mockImplementation(async (_source, _destination, _digest, tag) => {
      published.add(tag); return {outcome: 'present-at-expected-digest'}
    })
    const options: PublisherOptions = {
      cwd, revision, digest: 'sha256:' + 'b'.repeat(64), alias: alias(revision),
      repository: 'posthog-cloud', registry: destination.registry,
      force: [], regctl, helper: path.join(cwd, 'helper'), evidence: path.join(scratch, 'evidence'),
      budgets: {fetchMs: 30000, comparisonMs: 30000, maxBuffer: 1024 * 1024, registryMs: 30000, copySeconds: 1,
        readbackSeconds: 1, maxChannels: 1, concurrency: 1, channelMs: 120000, totalMs: 120000}
    }
    if (mode === 'slow policy fetch') options.budgets.comparisonMs = 1000
    const run = commands.command
    const fetches: {args: string[]; input?: string}[] = []
    const probes: {args: string[]; output: string}[] = []
    let fetched = false
    let policyFetchMs = 0
    let discoveryTimeoutMs = 0
    jest.spyOn(commands, 'command').mockImplementation(async (executable, args, configuration) => {
      if (mode.includes('probe failure') && fetched && executable === 'git' && args[0] === 'cat-file' && args.includes('--batch-check=%(objectname) %(objecttype)')) {
        throw new Error('post-fetch availability probe timed out')
      }
      if (executable === 'git' && args[0] === 'fetch') fetches.push({args, input: configuration.input})
      const delayed = mode === 'slow policy fetch' && executable === 'git' && args[0] === 'fetch' && configuration.input?.includes(policyBlob)
      const started = performance.now()
      if (delayed) await new Promise<void>(resolve => setTimeout(resolve, 2000))
      if (executable === 'git' && args[0] === 'log' && args.includes('--format=%H')) discoveryTimeoutMs = configuration.timeoutMs
      try {
        const output = await run(executable, args, configuration)
        if (delayed) policyFetchMs = performance.now() - started
        if (executable === 'git') probes.push({args, output})
        return output
      } finally {
        if (executable === 'git' && args[0] === 'fetch') fetched = true
      }
    })
    const [result] = await publishChannels(options)
    if (mode === 'available' || mode === 'slow policy fetch' || mode === 'missing subtrees') {
      expect(result).toMatchObject({decision: 'published', outcome: 'present-at-expected-digest'})
      if (mode === 'slow policy fetch') {
        expect(policyFetchMs).toBeGreaterThan(options.budgets.comparisonMs)
        expect(policyFetchMs).toBeLessThan(options.budgets.fetchMs)
        expect(discoveryTimeoutMs).toBeGreaterThan(options.budgets.comparisonMs)
        process.stdout.write(JSON.stringify({comparisonMs: options.budgets.comparisonMs, fetchMs: options.budgets.fetchMs, policyFetchMs, discoveryTimeoutMs}) + '\n')
      }
      expect(() => git(cwd, 'cat-file', '-e', tree)).not.toThrow()
      expect(() => git(cwd, 'cat-file', '-e', policyBlob)).not.toThrow()
      expect(published.has(options.alias)).toBe(true)
      if (mode === 'available') {
        const missingRoot = probes.findIndex(probe => probe.args[0] === 'cat-file' && probe.output.split('\n').some(line => line.endsWith(' missing')))
        expect(missingRoot).toBeGreaterThanOrEqual(0)
        expect(probes[missingRoot + 1].args[0]).toBe('fetch')
      }
      expect(fetches.some(fetch => fetch.args.includes('--filter=blob:none') && fetch.args.includes('--stdin'))).toBe(true)
      expect(fetches.some(fetch => !fetch.args.some(arg => arg.startsWith('--filter=')) && fetch.input?.includes(policyBlob))).toBe(true)
      const comparison = await new SourceHistory(cwd, options.budgets).compare(base, revision)
      expect(comparison.policies.map(policy => policyDigest(policy!.filters.worker))).toEqual([policyDigest(['worker/**']), policyDigest(['new-worker/**'])])
      expect(new Filter(JSON.stringify({worker: ['new-worker/**']})).match(comparison.files).worker).toEqual([])
    } else {
      expect(result).toMatchObject({decision: 'blocked', reason: expect.stringContaining('remain unavailable after bounded fetch')})
      if (mode.includes('probe failure')) expect(result.reason).toContain('post-fetch availability probe timed out')
      if (!available) expect(result.reason).toContain('git: exited')
      expect(published.size).toBe(0)
    }
  }, 15000)
})

import {execFileSync} from 'child_process'
import {chmodSync, mkdirSync, mkdtempSync, rmSync, unlinkSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import {publishChannels, PublisherOptions} from '../src/shared-image-publisher'
import {approvedImages, CANONICAL_SOURCE_REPOSITORY, POLICY_PATH} from '../src/shared-image'
import {ReleaseRegistry} from '../src/shared-image-registry'
import * as commands from '../src/shared-image-command'

jest.unmock('../src/shared-image-command')
let scratch: string
const git = (cwd: string, ...args: string[]): string => execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', ...args], {
  cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
}).trim()
beforeEach(() => { scratch = mkdtempSync(path.join(tmpdir(), 'shared-image-fetch-')) })
afterEach(() => { jest.restoreAllMocks(); rmSync(scratch, {recursive: true, force: true}) })

describe('publisher bounded tree fetching with the real command runner', () => {
  test.each(['available', 'missing', 'probe failure', 'fetch and probe failure'])('bounded tree fetch: %s', async mode => {
    const available = mode === 'available' || mode === 'probe failure'
    const cwd = path.join(scratch, 'executing')
    const origin = path.join(scratch, 'origin.git')
    mkdirSync(cwd)
    git(cwd, 'init', '-b', 'main'); git(cwd, 'config', 'user.name', 'Fixture'); git(cwd, 'config', 'user.email', 'fixture@example.invalid')
    git(scratch, 'init', '--bare', origin)
    git(scratch, '--git-dir', origin, 'config', 'uploadpack.allowFilter', 'true')
    git(scratch, '--git-dir', origin, 'config', 'uploadpack.allowAnySHA1InWant', 'true')
    git(cwd, 'remote', 'add', 'origin', `file://${origin}`)
    const put = (name: string, value: string): void => {
      const file = path.join(cwd, name); mkdirSync(path.dirname(file), {recursive: true}); writeFileSync(file, value)
    }
    const commit = (): string => { git(cwd, 'add', '-A'); git(cwd, 'commit', '-m', 'fixture'); return git(cwd, 'rev-parse', 'HEAD') }
    const alias = (revision: string): string => `r${git(cwd, 'rev-list', '--first-parent', '--count', revision).padStart(12, '0')}-${revision.slice(0, 6)}`
    put(POLICY_PATH, JSON.stringify({version: 1, filters: {worker: ['worker/**']}, images: {'posthog-cloud': {channels: {worker: {repository: 'workers/worker', filter: 'worker'}}}}}))
    put('worker/run.py', 'base'); const base = commit()
    git(cwd, 'push', 'origin', 'main')
    put('worker/run.py', 'unpublished'); const relevant = commit()
    put('unrelated.txt', 'later successful build'); const revision = commit()
    if (available) git(cwd, 'push', 'origin', 'main')
    const tree = git(cwd, 'rev-parse', `${relevant}^{tree}`)
    const treeFile = path.join(cwd, '.git/objects', tree.slice(0, 2), tree.slice(2))
    unlinkSync(treeFile)
    const regctl = path.join(scratch, 'regctl')
    writeFileSync(regctl, '#!/bin/sh\nexit 1\n'); chmodSync(regctl, 0o755)
    const destination = {owner: 'worker', repository: 'workers/worker', registry: 'registry.example.com', replicas: []}
    const published = new Set<string>()
    jest.spyOn(ReleaseRegistry.prototype, 'list').mockResolvedValue({tags: new Set([alias(base)]), nonempty: true})
    jest.spyOn(ReleaseRegistry.prototype, 'read').mockResolvedValue('sha256:' + 'a'.repeat(64))
    jest.spyOn(ReleaseRegistry.prototype, 'identity').mockImplementation(async (_registry, repository, digest) => ({
      revision: repository === destination.repository ? base : revision, digest
    }))
    jest.spyOn(ReleaseRegistry.prototype, 'publish').mockImplementation(async (_source, _destination, _digest, tag) => {
      published.add(tag); return {outcome: 'present-at-expected-digest'}
    })
    const options: PublisherOptions = {
      cwd, revision, digest: 'sha256:' + 'b'.repeat(64), alias: alias(revision),
      approved: approvedImages('posthog-cloud', destination.registry, destination.registry, JSON.stringify([destination])),
      force: [], regctl, helper: path.join(cwd, 'helper'), evidence: path.join(scratch, 'evidence'),
      budgets: {fetchMs: 30000, comparisonMs: 30000, maxBuffer: 1024 * 1024, registryMs: 30000, copySeconds: 1,
        readbackSeconds: 1, maxChannels: 1, concurrency: 1, channelMs: 120000, totalMs: 120000}
    }
    if (mode.includes('probe failure')) {
      const run = commands.command
      let fetched = false
      jest.spyOn(commands, 'command').mockImplementation(async (executable, args, configuration) => {
        if (fetched && executable === 'git' && args[0] === 'cat-file' && args.includes('--batch-check=%(objectname) %(objecttype)')) {
          throw new Error('post-fetch availability probe timed out')
        }
        try { return await run(executable, args, configuration) } finally {
          if (executable === 'git' && args[0] === 'fetch') fetched = true
        }
      })
    }
    expect(options.approved['posthog-cloud'].sourceRepository).toBe(CANONICAL_SOURCE_REPOSITORY)
    const [result] = await publishChannels(options)
    if (mode === 'available') {
      expect(result).toMatchObject({decision: 'published', outcome: 'present-at-expected-digest'})
      expect(() => git(cwd, 'cat-file', '-e', tree)).not.toThrow()
      expect(published.has(options.alias)).toBe(true)
    } else {
      expect(result).toMatchObject({decision: 'blocked', reason: expect.stringContaining('remain unavailable after bounded fetch')})
      if (mode.includes('probe failure')) expect(result.reason).toContain('post-fetch availability probe timed out')
      if (!available) expect(result.reason).toContain('git: exited')
      expect(published.size).toBe(0)
    }
  })
})

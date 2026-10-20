import {execFileSync} from 'child_process'
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import {createHash} from 'crypto'
import * as yaml from 'js-yaml'
import {command, CommandOptions} from '../src/shared-image-command'
import {SourceHistory} from '../src/shared-image-history'
import {publishChannels, PublisherOptions, validateRequests} from '../src/shared-image-publisher'
import {approvedImages, CANONICAL_SOURCE_REPOSITORY, loadPolicy, POLICY_PATH, policyDigest} from '../src/shared-image'

jest.mock('../src/shared-image-command')
const external = command as jest.MockedFunction<typeof command>
let repo: string
let options: PublisherOptions
let tags: Map<string, Map<string, string>>
let manifests: Map<string, string>
let base: string
const git = (...args: string[]): string => execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', ...args], {
  cwd: repo, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']
}).trim()
const put = (name: string, text: string): void => {
  mkdirSync(path.dirname(path.join(repo, name)), {recursive: true})
  writeFileSync(path.join(repo, name), text)
}
const commit = (): string => { git('add', '-A'); git('commit', '--allow-empty', '-m', 'fixture'); return git('rev-parse', 'HEAD') }
const policy = (paths = ['worker/**'], extra: Record<string, unknown> = {}): string => yaml.dump({
  version: 1, filters: {worker: paths, other: ['other/**']},
  images: {'posthog-cloud': {channels: {worker: {repository: 'workers/worker', filter: 'worker', ...extra},
    other: {repository: 'workers/other', filter: 'other'}}}}
})
const image = (revision: string, source = `https://github.com/${CANONICAL_SOURCE_REPOSITORY}`): string => {
  const raw = JSON.stringify({schemaVersion: 2, annotations: {'org.opencontainers.image.revision': revision, 'org.opencontainers.image.source': source}})
  const digest = `sha256:${createHash('sha256').update(raw).digest('hex')}`
  manifests.set(digest, raw)
  return digest
}
const alias = (revision: string): string => `r${git('rev-list', '--first-parent', '--count', revision).padStart(12, '0')}-${revision.slice(0, 6)}`
const build = (): void => {
  options.revision = git('rev-parse', 'HEAD')
  options.digest = image(options.revision)
  options.alias = alias(options.revision)
}
const seed = (revision: string): void => {
  const digest = image(revision)
  for (const repository of ['workers/worker', 'workers/other']) tags.get(repository)?.set(alias(revision), digest)
}
const invoke = async (executable: string, args: string[], configuration: CommandOptions): Promise<string> => {
  if (executable === 'git') return jest.requireActual<typeof import('../src/shared-image-command')>('../src/shared-image-command').command('git', args, configuration)
  if (executable === 'aws') {
    const repository = args[args.indexOf('--repository-name') + 1]
    const entries = tags.get(repository) ?? new Map<string, string>()
    if (args[1] === 'list-images') {
      const all = [...entries].map(([imageTag, imageDigest]) => ({imageTag, imageDigest}))
      const offset = args.includes('--next-token') ? Number(args[args.indexOf('--next-token') + 1]) : 0
      return JSON.stringify({imageIds: all.slice(offset, offset + 1), ...(offset + 1 < all.length ? {nextToken: String(offset + 1)} : {})})
    }
    const tag = args.find(argument => argument.startsWith('imageTag='))?.slice(9) ?? ''
    return entries.get(tag) ?? 'None'
  }
  if (executable === 'client') {
    const digest = args[2].split('@')[1]
    const raw = manifests.get(digest)
    if (!raw) throw new Error('missing source image')
    return raw
  }
  if (executable === 'helper') {
    const env = configuration.env ?? {}
    const entries = tags.get(env.ECR_REPO ?? '') as Map<string, string>
    const existing = entries.get(env.ORDERED_ALIAS ?? '')
    const outcome = existing && existing !== env.EXPECTED_DIGEST ? 'integrity-mismatch' : 'present-at-expected-digest'
    if (outcome === 'present-at-expected-digest') entries.set(env.ORDERED_ALIAS ?? '', env.EXPECTED_DIGEST ?? '')
    writeFileSync(env.GITHUB_OUTPUT ?? '', `outcome=${outcome}\n`)
    return ''
  }
  throw new Error(`Unexpected external command: ${executable}`)
}

beforeEach(() => {
  repo = mkdtempSync(path.join(tmpdir(), 'shared-image-publisher-'))
  git('init', '-b', 'main'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
  tags = new Map(['workers/worker', 'workers/other'].map(repository => [repository, new Map<string, string>()]))
  manifests = new Map()
  options = {
    cwd: repo, revision: '', digest: '', alias: '', force: [],
    approved: approvedImages('posthog-cloud', 'registry.example.com', 'registry.example.com', JSON.stringify([
      {owner: 'worker', repository: 'workers/worker', registry: 'registry.example.com', replicas: ['replica.example.com']},
      {owner: 'other', repository: 'workers/other', registry: 'registry.example.com', replicas: ['replica.example.com']}
    ])),
    budgets: {fetchMs: 30000, comparisonMs: 30000, maxBuffer: 1024 * 1024, registryMs: 30000, copySeconds: 1,
      readbackSeconds: 1, maxChannels: 4, concurrency: 2, channelMs: 60000, totalMs: 120000},
    regctl: 'regctl', helper: 'helper', evidence: path.join(repo, 'evidence')
  }
  put(POLICY_PATH, policy()); put('worker/run.py', 'base'); base = commit(); seed(base)
  external.mockReset().mockImplementation(invoke)
})
afterEach(() => rmSync(repo, {recursive: true, force: true}))

describe('shared-image publication', () => {
  test('historical policy reads preserve literal YAML bytes and accept executable regular files', async () => {
    const text = 'version: 1\nimages:\n  posthog-cloud:\n    channels:\n      worker:\n        repository: workers/worker\n        filter: worker\nfilters:\n  worker:\n    - |+\n      worker/**\n\n\n'
    put(POLICY_PATH, text)
    git('add', '-A'); git('update-index', '--chmod=+x', POLICY_PATH); git('commit', '-m', 'policy bytes')
    const current = await new SourceHistory(repo, options.budgets).current(git('rev-parse', 'HEAD'))
    expect(current.filters.worker).toEqual(['worker/**\n\n\n'])
    expect(policyDigest(current.filters.worker)).toBe(policyDigest(loadPolicy(text).filters.worker))
  })

  test.each([true, false])('unpublished relevant changes recover after build success=%s', async success => {
    put('worker/run.py', 'relevant'); commit(); build()
    const firstDigest = options.digest
    const firstAlias = options.alias
    if (success) expect((await publishChannels(options)).find(result => result.channel.endsWith('/worker'))?.decision).toBe('published')
    else expect(tags.get('workers/worker')!.has(firstAlias)).toBe(false)
    put('unrelated.txt', 'unrelated'); commit(); build()
    const results = await publishChannels(options)
    expect(results.find(result => result.channel.endsWith('/worker'))?.decision).toBe(success ? 'unchanged' : 'published')
    expect(results.find(result => result.channel.endsWith('/other'))?.decision).toBe('unchanged')
    expect(tags.get('workers/worker')?.get(success ? firstAlias : options.alias)).toBe(success ? firstDigest : options.digest)
  })

  test.each(['reverted policy', 'destination rebind'])('%s affects only the selected channel', async mode => {
    if (mode === 'destination rebind') {
      const source = options.approved['posthog-cloud']
      source.destinations = [...source.destinations, {...source.destinations[0], repository: 'workers/rebound'}]
      tags.set('workers/rebound', new Map([[alias(base), image(base)]]))
      const changed = loadPolicy(policy())
      changed.images['posthog-cloud'].channels.worker.repository = 'workers/rebound'
      put(POLICY_PATH, yaml.dump(changed)); commit(); build()
      expect(await publishChannels(options)).toEqual(expect.arrayContaining([
        expect.objectContaining({channel: 'posthog-cloud/worker', decision: 'blocked', reason: expect.stringContaining('historical destination changed')}),
        expect.objectContaining({channel: 'posthog-cloud/other', decision: 'unchanged'})
      ]))
      return
    }
    put(POLICY_PATH, policy(['worker/**', 'dependency/**'])); commit()
    put(POLICY_PATH, policy()); commit(); build()
    expect(await publishChannels(options)).toEqual(expect.arrayContaining([
      expect.objectContaining({channel: 'posthog-cloud/worker', decision: 'published'}),
      expect.objectContaining({channel: 'posthog-cloud/other', decision: 'unchanged'})
    ]))
  })

  test('explicit force preserves source identity and rejects unknown keys before copying', async () => {
    put('unrelated.txt', 'unrelated'); commit(); build(); options.force = ['posthog-cloud/worker']
    options.digest = image(options.revision, 'https://example.invalid/wrong')
    expect((await publishChannels(options)).find(result => result.channel.endsWith('/worker'))).toMatchObject({decision: 'blocked', reason: expect.stringContaining('canonical')})
    build()
    expect((await publishChannels(options)).find(result => result.channel.endsWith('/worker'))).toMatchObject({decision: 'published'})
    options.force = ['posthog-cloud/missing']
    await expect(publishChannels(options)).rejects.toThrow(/configured channel/)
    expect(() => validateRequests(loadPolicy(policy()), '*', undefined)).toThrow()
  })

  test.each(['invalid revision', 'ordinal mismatch', 'second parent', 'missing history', 'older build'])('frontier handles %s explicitly', async mode => {
    put('worker/run.py', 'relevant'); const head = commit(); build()
    const entries = tags.get('workers/worker')!
    entries.clear()
    if (mode === 'invalid revision') entries.set('r000000000002-abcdef', image('abcdef'))
    if (mode === 'ordinal mismatch') entries.set(`r000000000099-${base.slice(0, 6)}`, image(base))
    if (mode === 'missing history') entries.set('r000000000002-ffffff', image('f'.repeat(40)))
    if (mode === 'second parent') {
      git('checkout', '-b', 'feature', base); put('feature.txt', 'feature'); const second = commit()
      git('checkout', 'main'); git('merge', '--no-ff', 'feature', '-m', 'merge'); build()
      entries.set(alias(second), image(second))
    }
    if (mode === 'older build') {
      entries.set(alias(head), image(head)); git('checkout', '--detach', base); build()
    }
    const result = (await publishChannels(options)).find(row => row.channel.endsWith('/worker'))
    expect(result?.decision).toBe(mode === 'older build' ? 'older-revision' : 'blocked')
  })

  test('pagination selects the maximum, filters suffixes and cannot regress concurrent greater aliases', async () => {
    put('worker/run.py', 'one'); const first = commit(); seed(first)
    put('unrelated.txt', 'two'); commit(); build()
    tags.get('workers/worker')!.set('r999999999999-ffffff-extra', image(base))
    const result = await publishChannels(options)
    expect(result.find(row => row.channel.endsWith('/worker'))?.decision).toBe('unchanged')
    const saved = options.alias
    options.force = ['posthog-cloud/worker']; await publishChannels(options)
    git('checkout', '--detach', first); build(); await publishChannels(options)
    expect([...tags.get('workers/worker')!.keys()].filter(tag => /^r\d{12}-[a-f0-9]{6}$/.test(tag)).sort().pop()).toBe(saved)
  })

  test('one channel failure preserves other eligible attempts and emits no success receipt', async () => {
    put('worker/run.py', 'relevant'); put('other/file.py', 'relevant'); commit(); build()
    external.mockImplementation(async (exe, args, config) => {
      if (exe === 'helper' && config.env?.ECR_REPO === 'workers/worker') {
        writeFileSync(config.env.GITHUB_OUTPUT!, 'outcome=absent\n'); return ''
      }
      return invoke(exe, args, config)
    })
    expect(await publishChannels(options)).toEqual(expect.arrayContaining([
      expect.objectContaining({channel: 'posthog-cloud/worker', decision: 'blocked', outcome: 'absent'}),
      expect.objectContaining({channel: 'posthog-cloud/other', decision: 'published'})
    ]))
    expect(tags.get('workers/worker')!.has(options.alias)).toBe(false)
    external.mockImplementation(invoke)
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))).toMatchObject({decision: 'published', outcome: 'present-at-expected-digest'})
  })

  test.each(['rejected', 'missing outcome', 'invalid outcome'])('helper failure is unknown with its reason: %s', async mode => {
    put('worker/run.py', 'relevant'); commit(); build()
    external.mockImplementation(async (executable, args, config) => {
      if (executable === 'helper' && config.env?.ECR_REPO === 'workers/worker') {
        if (mode === 'rejected') throw new Error('copy helper crashed')
        if (mode === 'invalid outcome') writeFileSync(config.env.GITHUB_OUTPUT!, 'outcome=invalid\n')
        return ''
      }
      return invoke(executable, args, config)
    })
    const result = (await publishChannels(options)).find(row => row.channel.endsWith('/worker'))
    expect(result).toMatchObject({decision: 'blocked', outcome: 'unknown', reason: expect.stringContaining(mode === 'rejected' ? 'copy helper crashed' : 'no recognized outcome')})
    expect(tags.get('workers/worker')!.has(options.alias)).toBe(false)
  })

  test.each(['ordinary', 'seed', 'retry after advancement', 'missing seed', 'conflict', 'missing historical policy', 'missing fingerprint'])('bootstrap: %s', async mode => {
    const entries = tags.get('workers/worker')!
    entries.clear()
    if (['missing historical policy', 'missing fingerprint'].includes(mode)) {
      git('checkout', '--orphan', 'old')
      git('rm', '-rf', '.'); put('old.txt', 'old'); base = commit()
      put(POLICY_PATH, policy(['worker/**'], mode === 'missing historical policy' ? {bootstrapPolicyDigest: policyDigest(['worker/**'])} : {})); commit()
    }
    put('unrelated.txt', 'later build'); commit(); build()
    if (mode !== 'ordinary') options.bootstrap = {channel: 'posthog-cloud/worker', revision: base, digest: image(base)}
    if (mode === 'retry after advancement') { entries.set(alias(base), image(base)); entries.set(options.alias, options.digest) }
    if (mode === 'missing seed') entries.set(options.alias, options.digest)
    if (mode === 'conflict') entries.set(alias(base), image(base, 'https://example.invalid/conflict'))
    const result = (await publishChannels(options)).find(row => row.channel.endsWith('/worker'))!
    const succeeds = ['seed', 'retry after advancement', 'missing historical policy'].includes(mode)
    expect(result.decision).toBe(succeeds ? mode === 'retry after advancement' ? 'present' : 'published' : 'blocked')
    if (succeeds) expect(JSON.parse(readFileSync(path.join(options.evidence, 'bootstrap/posthog-cloud/worker.json'), 'utf8'))).toEqual({
      version: 1, sourceRepository: CANONICAL_SOURCE_REPOSITORY, sourceImage: 'registry.example.com/posthog-cloud',
      destination: options.approved['posthog-cloud'].destinations[0], policyRevision: options.revision,
      policyDigest: policyDigest(['worker/**']), seedRevision: base, ordinal: Number(alias(base).slice(1, 13)),
      tag: alias(base), digest: image(base), outcome: 'present-at-expected-digest'
    })
  })

  test.each([true, false])('seed predating manifest=%s uses the immutable fingerprint until adoption', async predatesManifest => {
    if (predatesManifest) git('rm', POLICY_PATH)
    else {
      const previous = loadPolicy(policy())
      delete previous.images['posthog-cloud'].channels.worker
      put(POLICY_PATH, yaml.dump(previous))
    }
    const seedRevision = commit(); seed(seedRevision)
    put(POLICY_PATH, policy(['worker/**'], {bootstrapPolicyDigest: policyDigest(['worker/**'])})); commit(); build()
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))?.decision).toBe('unchanged')
    put('worker/run.py', 'relevant'); commit(); build()
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))?.decision).toBe('published')
    put(POLICY_PATH, policy(['worker/**', 'dependency/**'], {bootstrapPolicyDigest: policyDigest(['worker/**'])})); commit(); build()
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))?.decision).toBe('published')
    put(POLICY_PATH, policy(['worker/**', 'dependency/**'], {bootstrapPolicyDigest: 'f'.repeat(64)})); commit(); build()
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))).toMatchObject({decision: 'blocked', reason: expect.stringContaining('cannot change')})
  })

  test.each(['destination', 'fan-out'])('%s errors fail before any channel copy', async mode => {
    put('unrelated.txt', mode); commit(); build()
    if (mode === 'destination') options.approved['posthog-cloud'].destinations = []
    else options.budgets.maxChannels = 1
    await expect(publishChannels(options)).rejects.toThrow(mode === 'destination' ? /worker.*approved destination/ : /fan-out/)
    expect([...tags.values()].every(entries => !entries.has(options.alias))).toBe(true)
  })
})

import {execFileSync} from 'child_process'
import {mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, chmodSync, existsSync} from 'fs'
import {tmpdir} from 'os'
import * as path from 'path'
import {createHash} from 'crypto'
import * as yaml from 'js-yaml'
import {command, CommandOptions} from '../src/shared-image-command'
import {ReleaseRegistry} from '../src/shared-image-registry'
import {SourceHistory} from '../src/shared-image-history'
import {publishChannels, PublisherOptions, validateRequests} from '../src/shared-image-publisher'
import {CANONICAL_SOURCE_REPOSITORY, loadPolicy, POLICY_PATH, policyDigest} from '../src/shared-image'

jest.mock('../src/shared-image-command')
const external = command as jest.MockedFunction<typeof command>
let repo: string
let options: PublisherOptions
let tags: Map<string, Map<string, string>>
let untagged: Map<string, Set<string>>
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
const image = (revision: string, source = `https://github.com/${CANONICAL_SOURCE_REPOSITORY}`, marker = ''): string => {
  const raw = JSON.stringify({schemaVersion: 2, annotations: {'org.opencontainers.image.revision': revision, 'org.opencontainers.image.source': source}, ...(marker ? {marker} : {})})
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
    if (args[args.indexOf('--registry-id') + 1] !== '123456789012') throw new Error('Unexpected fixture registry ID')
    const repository = args[args.indexOf('--repository-name') + 1]
    const entries = tags.get(repository) ?? new Map<string, string>()
    if (args[1] === 'list-images') {
      const all = [
        ...Array.from(untagged.get(repository) ?? [], imageDigest => ({imageDigest})),
        ...[...entries].map(([imageTag, imageDigest]) => ({imageTag, imageDigest}))
      ]
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
    if (args[1] === 'read') {
      const outcome = !existing ? 'absent' : existing === env.EXPECTED_DIGEST ? 'present-at-expected-digest' : 'integrity-mismatch'
      writeFileSync(env.GITHUB_OUTPUT ?? '', `outcome=${outcome}\n`)
      return existing ?? 'None'
    }
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
  untagged = new Map([...tags.keys()].map(repository => [repository, new Set<string>()]))
  manifests = new Map()
  options = {
    cwd: repo, revision: '', digest: '', alias: '', force: [],
    repository: 'posthog-cloud', registry: '123456789012.dkr.ecr.us-east-1.amazonaws.com',
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
    const current = await new SourceHistory(repo, {...options.budgets, retryDelaysMs: [0, 0]}).current(git('rev-parse', 'HEAD'))
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

  test.each(['reverted policy', 'merged policy', 'destination rebind'])('%s affects only the selected channel', async mode => {
    if (mode === 'destination rebind') {
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
    if (mode === 'merged policy') git('checkout', '-b', 'policy-change', base)
    put(POLICY_PATH, policy(['worker/**', 'dependency/**'])); commit()
    if (mode === 'merged policy') {
      git('checkout', 'main'); put('unrelated.txt', 'main'); commit()
      git('merge', '--no-ff', 'policy-change', '-m', 'merge policy')
    } else {
      put(POLICY_PATH, policy()); commit()
    }
    build()
    expect(await publishChannels(options)).toEqual(expect.arrayContaining([
      expect.objectContaining({channel: 'posthog-cloud/worker', decision: 'published'}),
      expect.objectContaining({channel: 'posthog-cloud/other', decision: 'unchanged'})
    ]))
  })

  test.each(['wrong source', 'wrong revision', 'corrupt manifest bytes'])('explicit force preserves source identity: %s', async mode => {
    put('unrelated.txt', 'unrelated'); commit(); build(); options.force = ['posthog-cloud/worker']
    if (mode === 'wrong source') options.digest = image(options.revision, 'https://example.invalid/wrong')
    if (mode === 'wrong revision') options.digest = image(base)
    if (mode === 'corrupt manifest bytes') manifests.set(options.digest, JSON.stringify({...JSON.parse(manifests.get(options.digest)!), marker: 'tampered bytes'}))
    expect((await publishChannels(options)).find(result => result.channel.endsWith('/worker'))).toMatchObject({
      decision: 'blocked', reason: expect.stringContaining(mode === 'wrong source' ? 'canonical' : mode === 'wrong revision' ? 'Image revision differs' : 'Manifest digest mismatch')
    })
    expect(tags.get('workers/worker')!.has(options.alias)).toBe(false)
    build()
    expect((await publishChannels(options)).find(result => result.channel.endsWith('/worker'))).toMatchObject({decision: 'published'})
    options.force = ['posthog-cloud/missing']
    await expect(publishChannels(options)).rejects.toThrow(/configured channel/)
    expect(() => validateRequests(loadPolicy(policy()), '*', undefined)).toThrow()
  })

  test.each(['same digest', 'different digest', 'slow read'])('equal-revision rerun with %s preserves exact publication identity', async mode => {
    put('worker/run.py', 'relevant'); commit(); build(); seed(options.revision)
    const existing = options.digest
    let elapsedMs = 0
    if (mode === 'slow read') {
      options.budgets.registryMs = 1
      options.budgets.readbackSeconds = 5
      options.helper = path.resolve(__dirname, '../../../scripts/ordered-image-release.sh')
      put('shims/aws', '#!/usr/bin/env bash\nfor ((i=0; i<5000; i++)); do :; done\nprintf "%s\\n" "$EXPECTED_DIGEST"\n')
      put('shims/timeout', '#!/usr/bin/env bash\n[[ "$1" = --foreground && "$2" = --kill-after=5s && "$3" = "${READBACK_TIMEOUT_SECONDS}s" ]] || exit 64\nshift 3\nexec "$@"\n')
      for (const name of ['aws', 'timeout']) chmodSync(path.join(repo, 'shims', name), 0o755)
      external.mockImplementation(async (exe, args, config) => {
        if (exe === 'helper' && args[1] === 'read' && config.env?.ECR_REPO === 'workers/worker') {
          expect(config.timeoutMs).toBe((options.budgets.readbackSeconds + 15) * 1000)
          const started = performance.now()
          const result = await jest.requireActual<typeof import('../src/shared-image-command')>('../src/shared-image-command').command(exe, args, {
            ...config, env: {...config.env, PATH: `${path.join(repo, 'shims')}:${process.env.PATH}`}
          })
          elapsedMs = performance.now() - started
          return result
        }
        return invoke(exe, args, config)
      })
    }
    if (mode === 'different digest') options.digest = image(options.revision, `https://github.com/${CANONICAL_SOURCE_REPOSITORY}`, 'different build')
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))).toEqual({
      channel: 'posthog-cloud/worker', decision: mode === 'different digest' ? 'blocked' : 'present',
      outcome: mode === 'different digest' ? 'integrity-mismatch' : 'present-at-expected-digest', tag: options.alias, digest: options.digest
    })
    expect(tags.get('workers/worker')!.get(options.alias)).toBe(existing)
    if (mode === 'slow read') {
      expect(elapsedMs).toBeGreaterThan(options.budgets.registryMs)
      expect(elapsedMs).toBeLessThan(options.budgets.readbackSeconds * 1000)
    }
  })

  test.each(['invalid revision', 'ordinal mismatch', 'second parent', 'higher second parent', 'missing history', 'older build'])('frontier handles %s explicitly', async mode => {
    put('worker/run.py', 'relevant'); const head = commit(); build()
    const entries = tags.get('workers/worker')!
    entries.clear()
    if (mode === 'invalid revision') entries.set('r000000000002-abcdef', image('abcdef'))
    if (mode === 'ordinal mismatch') entries.set(`r000000000099-${base.slice(0, 6)}`, image(base))
    if (mode === 'missing history') entries.set('r000000000002-ffffff', image('f'.repeat(40)))
    if (mode === 'second parent' || mode === 'higher second parent') {
      git('checkout', '-b', 'feature', base)
      let second = base
      for (let index = 0; index < (mode === 'higher second parent' ? 3 : 1); index++) {
        put('feature.txt', `feature ${index}`); second = commit()
      }
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

  test.each([
    ['RepositoryNotFoundException', 'missing'],
    ['AccessDeniedException', 'denied'],
    ['AccessDenied', 'denied'],
    ['ServiceUnavailableException', 'unknown']
  ])('frontier access failure %s blocks only its channel as %s', async (failure, classification) => {
    put('worker/run.py', 'relevant'); put('other/file.py', 'relevant'); commit(); build()
    external.mockImplementation(async (exe, args, config) => {
      if (exe === 'aws' && args[1] === 'list-images' && args[args.indexOf('--repository-name') + 1] === 'workers/worker') {
        throw new Error(failure)
      }
      return invoke(exe, args, config)
    })
    const results = await publishChannels(options)
    expect(results).toContainEqual({channel: 'posthog-cloud/worker', decision: 'blocked', reason: expect.stringContaining(`posthog-cloud/worker: Error: workers/worker: ${classification} frontier lookup: Error: ${failure}`)})
    expect(results).toContainEqual(expect.objectContaining({channel: 'posthog-cloud/other', decision: 'published', digest: options.digest}))
    expect(tags.get('workers/worker')!.has(options.alias)).toBe(false)
  })

  test.each(['', 'registry.example.com', '123.dkr.ecr.us-east-1.amazonaws.com', 'https://123456789012.dkr.ecr.us-east-1.amazonaws.com', '123456789012.dkr.ecr.us-east-1.amazonaws.com/path'])('rejects registry hostname %s before commands', async registry => {
    build(); options.registry = registry
    await expect(publishChannels(options)).rejects.toThrow('Invalid authenticated ECR registry hostname')
    expect(external).not.toHaveBeenCalled()
  })

  test('one channel failure preserves other eligible attempts and emits no success receipt', async () => {
    put('worker/run.py', 'relevant'); put('other/file.py', 'relevant'); commit(); build()
    external.mockImplementation(async (exe, args, config) => {
      if (exe === 'helper' && args[1] === 'publish' && config.env?.ECR_REPO === 'workers/worker') {
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

  test.each(['rejected', 'timed out', 'missing outcome', 'invalid outcome', 'reported unknown', 'reported absent', 'reported integrity-mismatch'])('helper failure preserves its outcome and reason: %s', async mode => {
    put('worker/run.py', 'relevant'); commit(); build()
    external.mockImplementation(async (executable, args, config) => {
      if (executable === 'helper' && args[1] === 'publish' && config.env?.ECR_REPO === 'workers/worker') {
        if (mode === 'rejected') throw new Error('copy helper crashed')
        if (mode === 'timed out') return jest.requireActual<typeof import('../src/shared-image-command')>('../src/shared-image-command').command('helper', [
          '-c', 'printf "fixture primary diagnostic\\n" >&2; sleep 30'
        ], {...config, timeoutMs: 200})
        if (mode.startsWith('reported ')) return jest.requireActual<typeof import('../src/shared-image-command')>('../src/shared-image-command').command('helper', [
          '-c', 'printf "outcome=%s\\n" "$1" >> "$GITHUB_OUTPUT"; printf "fixture primary diagnostic\\n" >&2', 'fixture', mode.slice(9)
        ], config)
        if (mode === 'invalid outcome') writeFileSync(config.env.GITHUB_OUTPUT!, 'outcome=invalid\n')
        return ''
      }
      return invoke(executable, args, config)
    })
    const diagnostic = jest.spyOn(process.stderr, 'write').mockImplementation(() => true)
    try {
      const result = (await publishChannels(options)).find(row => row.channel.endsWith('/worker'))
      expect(result).toMatchObject({decision: 'blocked', outcome: mode.startsWith('reported ') ? mode.slice(9) : 'unknown', reason: expect.stringContaining(mode.startsWith('reported ') || mode === 'timed out' ? 'fixture primary diagnostic' : mode === 'rejected' ? 'copy helper crashed' : 'no recognized outcome')})
      if (mode.startsWith('reported ')) expect(diagnostic).toHaveBeenCalledWith('fixture primary diagnostic\n')
      if (mode === 'timed out') {
        expect(diagnostic).toHaveBeenCalledWith('fixture primary diagnostic')
        expect(result?.reason).toContain('helper: timed out')
      }
      expect(tags.get('workers/worker')!.has(options.alias)).toBe(false)
      expect(JSON.parse(readFileSync(path.join(options.evidence, 'results.json'), 'utf8'))).toContainEqual(result)
    } finally { diagnostic.mockRestore() }
  })

  test.each(['ordinary', 'seed', 'interrupted copy retry', 'stray tag', 'retry after advancement', 'retry without source', 'unavailable seed', 'missing seed', 'conflict', 'missing historical policy', 'missing fingerprint', 'wrong fingerprint', 'newer seed', 'seed digest from another revision', 'present seed from another revision', 'present seed with historical destination changed'])('bootstrap: %s', async mode => {
    const entries = tags.get('workers/worker')!
    entries.clear()
    if (mode === 'seed') tags.get('workers/other')!.clear()
    if (['missing historical policy', 'missing fingerprint', 'wrong fingerprint'].includes(mode)) {
      git('checkout', '--orphan', 'old')
      git('rm', '-rf', '.'); put('old.txt', 'old'); base = commit()
      put(POLICY_PATH, policy(['worker/**'], mode === 'missing historical policy' ? {bootstrapPolicyDigest: policyDigest(['worker/**'])} : mode === 'wrong fingerprint' ? {bootstrapPolicyDigest: 'f'.repeat(64)} : {})); commit()
    }
    if (mode === 'present seed with historical destination changed') {
      const previous = loadPolicy(policy())
      previous.images['posthog-cloud'].channels.worker.repository = 'workers/previous'
      put(POLICY_PATH, yaml.dump(previous)); base = commit()
      put(POLICY_PATH, policy())
    }
    put('unrelated.txt', 'later build'); commit(); build()
    if (mode !== 'ordinary') options.bootstrap = {channel: 'posthog-cloud/worker', revision: base, digest: image(base)}
    if (mode === 'retry after advancement' || mode === 'retry without source') { entries.set(alias(base), image(base)); entries.set(options.alias, options.digest) }
    if (mode === 'retry without source' || mode === 'unavailable seed') external.mockImplementation(async (exe, args, config) => {
      if (mode === 'retry without source' && exe === 'client' && args[2].includes('/posthog-cloud@')) throw new Error('source expired')
      if (mode === 'unavailable seed' && exe === 'helper' && args[1] === 'read') throw new Error('seed read failed')
      return invoke(exe, args, config)
    })
    if (mode === 'unavailable seed') entries.set(options.alias, options.digest)
    if (mode === 'missing seed') { untagged.get('workers/worker')!.add(image(base)); entries.set(options.alias, options.digest) }
    if (mode === 'stray tag') entries.set('latest', image(base))
    if (mode === 'conflict') entries.set(alias(base), image(base, 'https://example.invalid/conflict'))
    if (mode === 'seed digest from another revision' || mode === 'present seed from another revision') options.bootstrap!.digest = image(options.revision)
    if (mode.startsWith('present seed')) entries.set(alias(base), options.bootstrap!.digest)
    if (mode === 'newer seed') {
      put('future.txt', 'future seed'); const future = commit()
      options.bootstrap = {channel: 'posthog-cloud/worker', revision: future, digest: image(future)}
      git('checkout', '--detach', options.revision)
    }
    if (mode === 'interrupted copy retry') {
      const children = untagged.get('workers/worker')!
      const child = image(base, `https://github.com/${CANONICAL_SOURCE_REPOSITORY}`, 'child manifest')
      external.mockImplementation(async (exe, args, config) => {
        if (exe === 'helper' && args[1] === 'publish' && !children.size) {
          children.add(child)
          throw new Error('copy interrupted after child upload')
        }
        return invoke(exe, args, config)
      })
      expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))).toMatchObject({
        decision: 'blocked', outcome: 'unknown', reason: expect.stringContaining('copy interrupted after child upload')
      })
      expect(entries.size).toBe(0)
      expect(children).toEqual(new Set([child]))
      expect(existsSync(path.join(options.evidence, 'bootstrap/posthog-cloud/worker.json'))).toBe(false)
    }
    const result = (await publishChannels(options)).find(row => row.channel.endsWith('/worker'))!
    const succeeds = ['seed', 'interrupted copy retry', 'stray tag', 'retry after advancement', 'retry without source', 'missing historical policy'].includes(mode)
    expect(result.decision).toBe(succeeds ? mode.startsWith('retry') ? 'present' : 'published' : 'blocked')
    if (mode === 'interrupted copy retry' || mode === 'stray tag') {
      expect(result).toMatchObject({outcome: 'present-at-expected-digest', tag: alias(base), digest: image(base)})
      expect(entries.get(alias(base))).toBe(image(base))
    }
    if (mode === 'stray tag') expect(entries.get('latest')).toBe(image(base))
    if (['conflict', 'missing seed', 'unavailable seed'].includes(mode)) expect(result.reason).toContain(mode === 'conflict' ? 'seed digest conflict' : mode === 'missing seed' ? 'seed missing in nonempty destination' : 'seed readback unavailable: Error: seed read failed')
    if (mode === 'ordinary') expect(result.reason).toContain('empty ordered frontier requires explicit bootstrap')
    if (mode === 'newer seed') expect(result.reason).toContain('seed is newer than the executing revision')
    if (mode === 'wrong fingerprint') expect(result.reason).toContain('must match the reviewed current policy')
    if (mode.startsWith('present seed')) {
      expect(result.reason).toContain(mode === 'present seed from another revision' ? 'Image revision differs' : 'historical destination changed')
      expect(existsSync(path.join(options.evidence, 'bootstrap/posthog-cloud/worker.json'))).toBe(false)
    }
    if (mode === 'seed digest from another revision') {
      expect(result.reason).toContain('Image revision differs')
      expect(entries.size).toBe(0)
    }
    if (mode === 'seed') expect(tags.get('workers/other')!.size).toBe(0)
    if (succeeds) expect(JSON.parse(readFileSync(path.join(options.evidence, 'bootstrap/posthog-cloud/worker.json'), 'utf8'))).toEqual({
      version: 1, sourceRepository: CANONICAL_SOURCE_REPOSITORY, sourceImage: `${options.registry}/${options.repository}`,
      destination: {registry: options.registry, repository: 'workers/worker'}, policyRevision: options.revision,
      policyDigest: policyDigest(['worker/**']), seedRevision: base, ordinal: Number(alias(base).slice(1, 13)),
      tag: alias(base), digest: image(base), outcome: 'present-at-expected-digest'
    })
  })

  test.each(['manifest', 'channel'])('exact seed retry after filter change when seed predates %s', async gap => {
    const entries = tags.get('workers/worker')!
    entries.clear()
    if (gap === 'manifest') git('rm', POLICY_PATH)
    else {
      const previous = loadPolicy(policy())
      delete previous.images['posthog-cloud'].channels.worker
      put(POLICY_PATH, yaml.dump(previous))
    }
    const seedRevision = commit()
    const seedDigest = image(seedRevision)
    const adoption = {bootstrapPolicyDigest: policyDigest(['worker/**'])}
    put(POLICY_PATH, policy(['worker/**'], adoption)); commit(); build()
    const request = {channel: 'posthog-cloud/worker', revision: seedRevision, digest: seedDigest}
    options.bootstrap = request
    expect((await publishChannels(options)).find(row => row.channel === request.channel)?.decision).toBe('published')
    const receipt = path.join(options.evidence, 'bootstrap/posthog-cloud/worker.json')
    rmSync(receipt)
    put(POLICY_PATH, policy(['worker/**', 'dependency/**'], adoption)); commit(); build()
    options.bootstrap = undefined
    expect((await publishChannels(options)).find(row => row.channel === request.channel)?.decision).toBe('published')
    expect(entries.get(options.alias)).toBe(options.digest)
    expect(entries.get(alias(seedRevision))).toBe(seedDigest)
    external.mockClear()
    options.bootstrap = request
    const result = (await publishChannels(options)).find(row => row.channel === request.channel)!
    expect(result).toMatchObject({decision: 'present', outcome: 'present-at-expected-digest', tag: alias(seedRevision), digest: seedDigest})
    expect(JSON.parse(readFileSync(receipt, 'utf8'))).toEqual({
      version: 1, sourceRepository: CANONICAL_SOURCE_REPOSITORY, sourceImage: `${options.registry}/${options.repository}`,
      destination: {registry: options.registry, repository: 'workers/worker'}, policyRevision: options.revision,
      policyDigest: policyDigest(['worker/**', 'dependency/**']), seedRevision, ordinal: Number(alias(seedRevision).slice(1, 13)),
      tag: alias(seedRevision), digest: seedDigest, outcome: 'present-at-expected-digest'
    })
    expect(external.mock.calls.filter(([executable, args]) => executable === 'helper' && args[1] === 'publish')).toHaveLength(0)
  })

  test.each(['manifest', 'channel', 'missing fingerprint'])('seed predating %s uses the immutable fingerprint until adoption', async mode => {
    const predatesManifest = mode === 'manifest'
    if (predatesManifest) git('rm', POLICY_PATH)
    else {
      const previous = loadPolicy(policy())
      delete previous.images['posthog-cloud'].channels.worker
      put(POLICY_PATH, yaml.dump(previous))
    }
    const seedRevision = commit(); seed(seedRevision)
    put(POLICY_PATH, policy(['worker/**'], mode === 'missing fingerprint' ? {} : {bootstrapPolicyDigest: policyDigest(['worker/**'])})); commit(); build()
    if (mode === 'missing fingerprint') {
      expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))).toMatchObject({decision: 'blocked', reason: expect.stringContaining('missing bootstrapPolicyDigest for historical policy gap')})
      return
    }
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))?.decision).toBe('unchanged')
    put('worker/run.py', 'relevant'); commit(); build()
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))?.decision).toBe('published')
    put(POLICY_PATH, policy(['worker/**', 'dependency/**'], {bootstrapPolicyDigest: policyDigest(['worker/**'])})); commit(); build()
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))?.decision).toBe('published')
    put(POLICY_PATH, policy(['worker/**', 'dependency/**'], {bootstrapPolicyDigest: 'f'.repeat(64)})); commit(); build()
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))).toMatchObject({decision: 'blocked', reason: expect.stringContaining('cannot change')})
  })

  test.each([
    ['force scalar', '*', undefined],
    ['force unknown', ['posthog-cloud/missing'], undefined],
    ['force non-string', [7], undefined],
    ['null seed', [], null],
    ['primitive seed', [], 7],
    ['extra seed key', [], {channel: 'posthog-cloud/worker', revision: 'a'.repeat(40), digest: `sha256:${'a'.repeat(64)}`, extra: true}],
    ['unknown seed channel', [], {channel: 'posthog-cloud/missing', revision: 'a'.repeat(40), digest: `sha256:${'a'.repeat(64)}`}],
    ['short seed revision', [], {channel: 'posthog-cloud/worker', revision: 'a', digest: `sha256:${'a'.repeat(64)}`}],
    ['invalid seed digest', [], {channel: 'posthog-cloud/worker', revision: 'a'.repeat(40), digest: 'invalid'}],
    ['seed with force', ['posthog-cloud/worker'], {channel: 'posthog-cloud/worker', revision: 'a'.repeat(40), digest: `sha256:${'a'.repeat(64)}`}]
  ])('request validation rejects %s', (_name, force, bootstrap) => {
    expect(() => validateRequests(loadPolicy(policy()), force, bootstrap)).toThrow(String(_name).startsWith('force') ? 'Force requires' : 'Bootstrap requires')
  })

  test('omitted retry delays wait five and fifteen seconds before the third policy blob fetch publishes', async () => {
    put('worker/run.py', 'changed'); commit(); build()
    delete options.budgets.retryDelaysMs
    const policyBlob = git('rev-parse', `${options.revision}:${POLICY_PATH}`)
    let fetchAttempts = 0
    external.mockImplementation(async (executable, args, configuration) => {
      if (executable === 'git') {
        if (args[0] === 'cat-file' && args[1] === '-e' && args[2] === policyBlob && fetchAttempts < 3) {
          throw new Error('policy blob is missing')
        }
        if (args[0] === 'fetch') {
          if (++fetchAttempts < 3) throw new Error('transient policy blob fetch failure')
          return ''
        }
        return execFileSync('git', args, {
          cwd: repo, env: {...process.env, ...configuration.env}, input: configuration.input, encoding: 'utf8'
        })
      }
      return invoke(executable, args, configuration)
    })
    jest.useFakeTimers()
    const waits = jest.spyOn(global, 'setTimeout')
    try {
      const result = publishChannels(options).catch((error: unknown) => error)
      await jest.runAllTimersAsync()
      expect(waits.mock.calls.map(([, delay]) => delay)).toEqual([5000, 15000])
      expect(fetchAttempts).toBe(3)
      expect(await result).toContainEqual(expect.objectContaining({
        channel: 'posthog-cloud/worker', decision: 'published', outcome: 'present-at-expected-digest'
      }))
      expect(tags.get('workers/worker')!.get(options.alias)).toBe(options.digest)
    } finally {
      waits.mockRestore()
      jest.useRealTimers()
    }
  })

  test.each([
    ...[0, -1, 1.5, Infinity].map(value => ['registryMs', value] as const),
    ...[null, 0, '5 15', [], [0], [0, 0, 0], [-1, 0], [0, 1.5], [0, Infinity], [0, Number.MAX_SAFE_INTEGER + 1], [0, '15']]
      .map(value => ['retryDelaysMs', value] as const)
  ])('invalid budget %s=%j rejects before commands', async (name, value) => {
    build(); Object.assign(options.budgets, {[name]: value})
    await expect(publishChannels(options)).rejects.toThrow(`Invalid publisher budget: ${name}`)
    expect(external).not.toHaveBeenCalled()
  })

  test.each(['missing imageIds', 'numeric tag', 'numeric token', 'empty token', 'repeated token', 'read unknown', 'read absent', 'read malformed digest', 'invalid digest', 'missing annotations'])('registry responses reject %s', async mode => {
    put('worker/run.py', mode); commit(); build()
    let pages = 0
    external.mockImplementation(async (exe, args, config) => {
      if (exe === 'aws' && args[1] === 'list-images') {
        if (++pages > 6) throw new Error('fixture pagination limit reached')
        if (mode === 'missing imageIds') return '{}'
        if (mode === 'numeric tag') return JSON.stringify({imageIds: [{imageTag: 7}]})
        if (mode.endsWith('token') && (mode !== 'numeric token' || !args.includes('--next-token'))) return JSON.stringify({imageIds: [], nextToken: mode === 'numeric token' ? 7 : mode === 'empty token' ? '' : 'repeat'})
      }
      if (exe === 'helper' && args[1] === 'read') {
        if (mode === 'read unknown') throw new Error('frontier read failed')
        if (mode === 'read absent') { writeFileSync(config.env!.GITHUB_OUTPUT!, 'outcome=absent\n'); return 'None' }
        if (mode === 'read malformed digest') { writeFileSync(config.env!.GITHUB_OUTPUT!, 'outcome=integrity-mismatch\n'); return 'invalid' }
      }
      return invoke(exe, args, config)
    })
    if (mode === 'invalid digest') tags.get('workers/worker')!.set(alias(base), 'invalid')
    if (mode === 'missing annotations') {
      const raw = JSON.stringify({schemaVersion: 2})
      const digest = `sha256:${createHash('sha256').update(raw).digest('hex')}`
      manifests.set(digest, raw); tags.get('workers/worker')!.set(alias(base), digest)
    }
    const reasons: Record<string, string> = {
      'missing imageIds': 'invalid frontier page', 'numeric tag': 'Invalid frontier tag',
      'numeric token': 'invalid or repeated pagination token', 'empty token': 'invalid or repeated pagination token', 'repeated token': 'invalid or repeated pagination token',
      'read unknown': 'frontier readback unavailable', 'read absent': 'frontier disappeared during readback',
      'read malformed digest': 'frontier disappeared during readback', 'invalid digest': 'frontier disappeared during readback', 'missing annotations': 'invalid canonical source/revision metadata'
    }
    expect((await publishChannels(options)).find(row => row.channel.endsWith('/worker'))).toMatchObject({decision: 'blocked', reason: expect.stringContaining(reasons[mode])})
    expect(tags.get('workers/worker')!.has(options.alias)).toBe(false)
  })

  test('helper publication logs are forwarded while readback digests remain protocol data', async () => {
    const registry = new ReleaseRegistry(repo, options.regctl, options.helper, options.budgets, Infinity)
    const source = {repository: options.repository, registry: options.registry}
    const destination = {registry: options.registry, repository: 'workers/worker'}
    const output = jest.spyOn(process.stdout, 'write').mockImplementation(() => true)
    try {
      expect(await registry.read(destination, alias(base), image(base))).toEqual({outcome: 'present-at-expected-digest', digest: image(base)})
      expect(output).not.toHaveBeenCalled()
      external.mockImplementation(async (exe, args, config) => {
        const result = await invoke(exe, args, config)
        return exe === 'helper' && args[1] === 'publish' ? 'publication notice\n' : result
      })
      expect(await registry.publish(source, destination, image(base), alias(base))).toEqual({outcome: 'present-at-expected-digest'})
      expect(output).toHaveBeenCalledWith('publication notice\n')
    } finally { output.mockRestore() }
  })

  test('registry identity rejects an invalid digest before requesting manifest bytes', async () => {
    const registry = new ReleaseRegistry(repo, options.regctl, options.helper, options.budgets, Infinity)
    await expect(registry.identity('registry.example.com', 'posthog-cloud', 'invalid')).rejects.toThrow('Expected exact image digest')
    expect(external).not.toHaveBeenCalled()
  })

  test.each(['short revision', 'ordinal zero', 'ordinal too long', 'missing policy', 'symlink policy'])('history API rejects %s', async mode => {
    build()
    if (mode === 'symlink policy') { git('rm', POLICY_PATH); git('update-index', '--add', '--cacheinfo', `120000,${git('hash-object', '-w', '--stdin')},${POLICY_PATH}`); git('commit', '-m', 'symlink') }
    if (mode === 'missing policy') { git('rm', POLICY_PATH); commit() }
    const history = new SourceHistory(repo, {...options.budgets, retryDelaysMs: [0, 0]})
    if (mode.startsWith('ordinal')) external.mockImplementation(async (exe, args, config) => args.includes('--count') ? mode === 'ordinal zero' ? '0' : '1000000000000' : invoke(exe, args, config))
    const result = mode === 'missing policy' || mode === 'symlink policy' ? history.current(git('rev-parse', 'HEAD')) : history.alias(mode === 'short revision' ? 'abcdef' : options.revision)
    await expect(result).rejects.toThrow(mode === 'short revision' ? 'Expected full source revision' : mode.startsWith('ordinal') ? 'Source ordinal is out of range' : mode === 'missing policy' ? 'policy is missing' : 'expected a regular policy file')
  })

  test.each(['destination', 'fan-out', 'alias', 'digest'])('%s errors fail before any channel copy', async mode => {
    put('unrelated.txt', mode); commit(); build()
    if (mode === 'destination') { put(POLICY_PATH, policy(['worker/**'], {repository: 'posthog-cloud'})); commit(); build() }
    if (mode === 'fan-out') options.budgets.maxChannels = 1
    if (mode === 'alias') options.alias = `r000000000999-${options.revision.slice(0, 6)}`
    if (mode === 'digest') options.digest = 'invalid'
    await expect(publishChannels(options)).rejects.toThrow(mode === 'destination' ? /worker.*destination conflicts with source/ : mode === 'fan-out' ? /fan-out/ : mode === 'alias' ? /Built ordered alias differs/ : /successful build digest/)
    if (mode === 'alias' || mode === 'digest') expect(external.mock.calls.every(([executable]) => executable === 'git')).toBe(true)
    expect([...tags.values()].every(entries => !entries.has(options.alias))).toBe(true)
  })
})

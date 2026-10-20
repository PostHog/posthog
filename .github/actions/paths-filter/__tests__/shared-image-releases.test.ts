import {readFileSync} from 'fs'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {
  CANONICAL_SOURCE_REPOSITORY, ChangeStatus, ConsumerBinding, DestinationBinding, Filter, Paths,
  bindChannels, loadPolicy, policyDigest, projectLegacyFilters,
  serializePolicy, validateConsumerBinding
} from '../src/shared-image'

const destination: DestinationBinding = {
  owner: 'metadata', repository: 'posthog-temporal-workers/data-warehouse-metadata',
  registry: '123456789012.dkr.ecr.us-east-1.amazonaws.com',
  replicas: ['123456789012.dkr.ecr.eu-central-1.amazonaws.com']
}
const source = {
  sourceRepository: CANONICAL_SOURCE_REPOSITORY, registry: destination.registry, repository: 'posthog-cloud', destinations: [destination]
}
const approved = {'posthog-cloud': source}
const fixture = readFileSync(path.join(__dirname, 'fixtures/shared-image-policy.yaml'), 'utf8')
const literal = JSON.parse(readFileSync(path.join(__dirname, 'fixtures/shared-image-fingerprints.json'), 'utf8')) as
  {paths: Paths; bytes: string; sha256: string}[]
const policyWith = (entries: unknown): string => {
  const policy = yaml.load(fixture) as {filters: {dataWarehouseMetadata: unknown}}
  policy.filters.dataWarehouseMetadata = entries
  return yaml.dump(policy)
}

const consumer: ConsumerBinding = {
  owner: 'metadata', implementation: 'ordered-image-v2', sourceRepository: CANONICAL_SOURCE_REPOSITORY,
  sourceImage: `${source.registry}/${source.repository}`,
  logicalImageGroups: 1, repositories: [destination.registry, ...destination.replicas].map(registry => `${registry}/${destination.repository}`),
  inheritedGitFilters: []
}

describe('shared-image policy and legacy projection', () => {
  test.each([
    ['veto-only', ['!tests/**'], 1],
    ['unknown-status', [{typo: 'worker/**'}], 0],
    ['empty-status-array', [{added: []}], 0]
  ])('keeps legacy-only %s behavior without channel validation', (_name, entries, count) => {
    const document = yaml.load(fixture) as {filters: Record<string, unknown>}
    document.filters.legacyOnly = entries
    const policy = loadPolicy(yaml.dump(document))
    const result = new Filter(projectLegacyFilters(policy, '{}')).match([{filename: 'worker/run.py', status: ChangeStatus.Modified}])
    expect(result.legacyOnly).toHaveLength(count as number)
  })

  test.each([
    ['veto-only', ['!tests/**']],
    ['empty-status-array', [{added: []}]],
    ['unknown-status', [{typo: 'worker/**'}]],
    ['empty-status-key', [{'': 'worker/**'}]],
    ['empty-status-member', [{'added|': 'worker/**'}]],
    ['copied-status', [{copied: 'worker/**'}]],
    ['renamed-status', [{renamed: 'worker/**'}]],
    ['unmerged-status', [{unmerged: 'worker/**'}]],
    ['empty-pattern', ['']],
    ['empty-pattern-in-array', [{added: ['']}]],
    ['status-array-veto', [{added: ['worker/**', '!tests/**']}]]
  ])('rejects channel %s', (_name, entries) => {
    expect(() => loadPolicy(policyWith(entries))).toThrow()
  })

  test.each([
    ['positive-extglob', ['!(tests)/**']],
    ['catchall-with-veto', ['**', '!tests/**']],
    ['status-array', [{'added|modified': ['worker/**', 'pyproject.toml']}]],
    ['status-array-extglob', [{'added|modified': ['!(tests)/**']}]],
    ['status-veto', ['**', {deleted: '!worker/**'}]]
  ])('accepts channel %s with the vendored matcher', (_name, entries) => {
    expect(loadPolicy(policyWith(entries)).version).toBe(1)
  })

  test.each([
    ['version', (text: string): string => text.replace('version: 1', 'version: 2')],
    ['duplicate', (text: string): string => text + '\nversion: 1\n'],
    ['unknown-field', (text: string): string => text + '\nredirect: elsewhere\n'],
    ['reference', (text: string): string => text.replace('filter: dataWarehouseMetadata', 'filter: missing')],
    ['hostname', (text: string): string => text.replace(destination.repository, `registry.example.com/${destination.repository}:latest`)],
    ['channel-key', (text: string): string => text.replace('dw-metadata:', 'Bad_Key:')],
    ['bootstrap-digest', (text: string): string => text.replace('filter: dataWarehouseMetadata', 'filter: dataWarehouseMetadata\n        bootstrapPolicyDigest: bad')]
  ])('rejects invalid manifest %s', (_name, change) => {
    expect(() => loadPolicy(change(fixture))).toThrow()
  })

  test.each([
    ['missing', fixture.replace('version: 1\n', ''), "policy: missing required field 'version'"],
    ['unknown', fixture + '\nredirect: elsewhere\n', "policy: unknown field 'redirect'"]
  ])('names the %s field in shape errors', (_name, text, message) => {
    expect(() => loadPolicy(text)).toThrow(message)
  })

  test.each([
    ['canonical source', {...source, sourceRepository: 'other/source'}, 'source build has no approved canonical identity and coordinates'],
    ['empty source registry', {...source, registry: ''}, 'source build has no approved canonical identity and coordinates'],
    ['source destination collision', {...source, repository: destination.repository}, 'destination conflicts with source build repository'],
    ['empty owner', {...source, destinations: [{...destination, owner: ''}]}, 'destination has no approved owner, registry and replicas'],
    ['empty destination registry', {...source, destinations: [{...destination, registry: ''}]}, 'destination has no approved owner, registry and replicas']
  ])('rejects binding with %s', (_name, binding, message) => {
    expect(() => bindChannels(loadPolicy(fixture), {'posthog-cloud': binding})).toThrow(message as string)
  })

  test.each([
    ['unknown build', fixture.replace('posthog-cloud:', 'unknown-image:'), 'images.unknown-image: unknown build input'],
    ['prototype build', fixture.replace('posthog-cloud:', '__proto__:'), 'images.__proto__: unknown build input'],
    ['unapproved destination', fixture.replace(destination.repository, 'posthog-temporal-workers/unapproved'), 'expected one approved destination binding'],
    ['duplicate channel', fixture + '\n      another:\n        repository: posthog-temporal-workers/data-warehouse-metadata\n        filter: metadataAlias\n', 'conflicting destination']
  ])('parses but does not approve %s', (_name, text, message) => {
    const policy = loadPolicy(text)
    const authored = yaml.load(text) as {images: Record<string, unknown>}
    expect(Object.keys(policy.images)).toEqual(Object.keys(authored.images))
    expect(() => projectLegacyFilters(policy, '{}')).not.toThrow()
    expect(() => bindChannels(policy, approved)).toThrow(message)
  })

  test.each(['dw-metadata', '__proto__'])('enumerates explicitly approved prototype image and %s channel keys', name => {
    const policy = loadPolicy(fixture.replace('posthog-cloud:', '__proto__:').replace(/dataWarehouseMetadata/g, '__proto__'))
    const channels = policy.images['__proto__'].channels
    expect(Object.keys(channels)).toEqual(['dw-metadata'])
    const channel = channels['dw-metadata']
    policy.images['__proto__'].channels = Object.fromEntries([[name, channel]])
    const resolved = bindChannels(policy, Object.fromEntries([['__proto__', source]]))
    expect(Object.keys(resolved)).toEqual(['__proto__'])
    expect(Object.keys(resolved['__proto__'])).toEqual([name])
    expect(Object.prototype.hasOwnProperty.call(resolved, '__proto__')).toBe(true)
    expect(Object.prototype.hasOwnProperty.call(resolved['__proto__'], name)).toBe(true)
    expect(resolved['__proto__'][name]).toEqual(destination)
    expect(Object.keys(policy.filters)).toEqual(['__proto__', 'metadataAlias', 'dataWarehouse'])
    const projected = yaml.load(projectLegacyFilters(policy, '{}')) as Record<string, Paths>
    expect(Object.keys(projected)).toEqual(Object.keys(policy.filters))
    expect(projected['__proto__']).toEqual(policy.filters['__proto__'])
  })

  test('rejects independent channels whose regional replicas collide', () => {
    const document = yaml.load(fixture) as {images: Record<string, {channels: Record<string, {repository: string; filter: string}>}>}
    document.images.other = {channels: {other: {repository: destination.repository, filter: 'metadataAlias'}}}
    const other = {...source, registry: 'other-source.example.com', destinations: [{...destination, registry: 'other-origin.example.com'}]}
    expect(() => bindChannels(loadPolicy(yaml.dump(document)), {...approved, other})).toThrow(
      `images.other.channels.other: conflicting destination ${destination.replicas[0]}/${destination.repository}`
    )
  })

  test('the production workflow projects all legacy rules in their original order with identical patterns', () => {
    const workflow = yaml.load(readFileSync(path.join(__dirname, '../../../workflows/container-images-cd.yml'), 'utf8')) as
      {jobs: {posthog_build: {steps: {id?: string; with?: {filters?: string}}[]}}}
    const inline = workflow.jobs.posthog_build.steps.find(step => step.id === 'check_temporal_worker_changes')?.with?.filters
    expect(inline).toBeDefined()
    const inlineRules = yaml.load(inline!) as Record<string, Paths | null>
    const policy = loadPolicy(readFileSync(path.join(__dirname, '../../../shared-image-releases.yaml'), 'utf8'))
    const projected = yaml.load(projectLegacyFilters(policy, inline!)) as Record<string, Paths>
    expect(Object.keys(projected)).toEqual(Object.keys(inlineRules))
    for (const [name, rule] of Object.entries(inlineRules)) {
      expect({[name]: projected[name]}).toEqual({[name]: rule === null ? policy.filters[name] : rule})
    }
  })

  test('aliases, statuses and exclusions survive projection without changing legacy-only veto rules', () => {
    const policy = loadPolicy(fixture)
    expect(policy.filters.metadataAlias).toEqual(policy.filters.dataWarehouseMetadata)
    const inline = 'legacyVeto: ["!tests/**"]\n'
    const projected = projectLegacyFilters(policy, inline)
    const files = [
      {filename: 'worker/run.py', status: ChangeStatus.Modified},
      {filename: 'worker/tests/test.py', status: ChangeStatus.Modified},
      {filename: 'uv.lock', status: ChangeStatus.Added},
      {filename: 'uv.lock', status: ChangeStatus.Deleted},
      {filename: 'products/warehouse_sources/backend/source.py', status: ChangeStatus.Modified}
    ]
    const actual = new Filter(projected).match(files)
    expect(actual.dataWarehouseMetadata).toEqual([files[0], files[2]])
    expect(actual.metadataAlias).toEqual(actual.dataWarehouseMetadata)
    expect(actual.dataWarehouse).toEqual([files[4]])
    expect(actual.legacyVeto).toEqual(files)
    expect(() => projectLegacyFilters(policy, 'dataWarehouse: ["other/**"]')).toThrow(/duplicate policy/)
    expect(() => projectLegacyFilters(policy, 'missing: null')).toThrow(/unresolved policy reference/)
    const ordered = yaml.load(projectLegacyFilters(policy, 'before: ["a"]\ndataWarehouse: null\nafter: ["b"]')) as object
    expect(Object.keys(ordered).slice(0, 3)).toEqual(['before', 'dataWarehouse', 'after'])
    expect(new Filter(projected).match(files)).toEqual(new Filter(yaml.dump({...yaml.load(inline) as object, ...policy.filters})).match(files))
  })

  test.each(literal)('fingerprints literal canonical bytes $sha256', vector => {
    expect(serializePolicy(vector.paths)).toBe(vector.bytes)
    expect(policyDigest(vector.paths)).toBe(vector.sha256)
    if (vector.paths.length > 1) expect(policyDigest([...vector.paths].reverse())).not.toBe(vector.sha256)
  })

  test('canonicalizes status-object keys without sorting the path or status-value arrays', () => {
    expect(serializePolicy([{modified: 'b', added: ['c', 'a']}])).toBe('{"paths":[{"added":["c","a"],"modified":"b"}],"version":1}')
    const policy = loadPolicy(fixture)
    expect(policyDigest(policy.filters.metadataAlias)).toBe(policyDigest(policy.filters.dataWarehouseMetadata))
  })

  test.each([
    {implementation: 'service-repo-v1'}, {implementation: 'helm-release-v1'}, {implementation: 'legacy'},
    {logicalImageGroups: 2}, {owner: 'other'}, {sourceRepository: 'unrelated/source'}, {sourceImage: 'unapproved/image'},
    {repositories: [`${destination.registry}/${destination.repository}`]},
    {inheritedGitFilters: ['apps/base/service.yaml:source.includePaths']}
  ])('rejects unsupported consumer binding %j', change => {
    expect(() => validateConsumerBinding({...consumer, ...change}, source, destination)).toThrow()
  })

  test('one logical owner with all approved regional replicas passes', () => {
    const destinations = [{...destination, repository: 'other/image'}, destination]
    expect(bindChannels(loadPolicy(fixture), {'posthog-cloud': {...source, destinations}})).toEqual({
      'posthog-cloud': {'dw-metadata': destination}
    })
    expect(() => validateConsumerBinding(consumer, source, {...destination, replicas: [...destination.replicas]})).not.toThrow()
    expect(() => validateConsumerBinding(consumer, {...source, destinations: []}, destination)).toThrow('metadata.destination: unsupported source/consumer binding')
  })

  test('rejects conflicting independent owners in approved destination configuration', () => {
    const conflicting = {...source, destinations: [destination, {...destination, owner: 'other'}]}
    expect(() => bindChannels(loadPolicy(fixture), {'posthog-cloud': conflicting})).toThrow(/one approved destination binding/)
  })

  test('metadata removal-parent coverage stays distinct from the broader active warehouse rule', () => {
    const historical = readFileSync(path.join(__dirname, 'fixtures/metadata-removal-parent.yaml'), 'utf8')
    const current = loadPolicy(readFileSync(path.join(__dirname, '../../../shared-image-releases.yaml'), 'utf8'))
    const filter = new Filter(projectLegacyFilters(current, historical))
    const files = [
      {filename: 'products/warehouse_sources/backend/temporal/data_imports/source.py', status: ChangeStatus.Modified},
      {filename: 'products/warehouse_sources/backend/models.py', status: ChangeStatus.Modified},
      {filename: 'Dockerfile', status: ChangeStatus.Modified}
    ]
    const result = filter.match(files)
    expect(result.dataWarehouseMetadata).toEqual([files[0]])
    expect(result.dataWarehouse).toEqual(files)
    expect(current.images['posthog-cloud'].channels).toEqual({})
  })
})

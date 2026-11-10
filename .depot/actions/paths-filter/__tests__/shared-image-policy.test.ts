import {readFileSync} from 'fs'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {ChangeStatus} from '../src/file'
import {Filter} from '../src/filter'
import {loadPolicy, Paths, Policy, projectLegacyFilters} from '../src/shared-image-policy'

const fixture = readFileSync(path.join(__dirname, 'fixtures/shared-image-policy.yaml'), 'utf8')
const repository = (yaml.load(fixture) as Policy).images['posthog-cloud'].channels['dw-metadata'].repository
const policyWith = (entries: unknown): string => {
  const policy = yaml.load(fixture) as {filters: {dataWarehouseMetadata: unknown}}
  policy.filters.dataWarehouseMetadata = entries
  return yaml.dump(policy)
}

const workflow = yaml.load(readFileSync(path.join(__dirname, '../../../../.github/workflows/container-images-cd.yml'), 'utf8')) as
  {jobs: {posthog_build: {steps: {id?: string; with?: {filters?: string; 'shared-image-policy'?: string}}[]}}}
const productionInputs = workflow.jobs.posthog_build.steps.find(step => step.id === 'check_temporal_worker_changes')?.with
const productionPolicy = (): Policy => loadPolicy(readFileSync(path.join(__dirname, '../../../..', productionInputs!['shared-image-policy']!), 'utf8'))

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
    ['hostname', (text: string): string => text.replace(repository, `registry.example.com/${repository}:latest`)],
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

  test.each(['policy', 'legacy projection'])('rejects unrepresentable filter names in %s', boundary => {
    const operation = boundary === 'policy'
      ? () => loadPolicy(fixture.replace(/dataWarehouseMetadata/g, '__proto__'))
      : () => projectLegacyFilters(loadPolicy(fixture), '__proto__: ["worker/**"]')
    expect(operation).toThrow('filters.__proto__: not representable by the matcher')
  })

  test('the production workflow projects all legacy rules in their original order with identical patterns', () => {
    const inline = productionInputs?.filters
    expect(inline).toBeDefined()
    const inlineRules = yaml.load(inline!) as Record<string, Paths | null>
    const policy = productionPolicy()
    const projected = yaml.load(projectLegacyFilters(policy, inline!)) as Record<string, Paths>
    expect(Object.keys(projected)).toEqual(Object.keys({...inlineRules, ...policy.filters}))
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

  test('the metadata channel filter and the broader active warehouse rule stay distinct', () => {
    const filter = new Filter(projectLegacyFilters(productionPolicy(), '{}'))
    const files = [
      {filename: 'products/data_modeling/backend/views.py', status: ChangeStatus.Modified},
      {filename: 'products/warehouse_sources_queue/consumer.py', status: ChangeStatus.Modified},
      {filename: 'Dockerfile', status: ChangeStatus.Modified}
    ]
    const result = filter.match(files)
    expect(result.dataWarehouseMetadata).toEqual([files[0], files[2]])
    expect(result.dataWarehouse).toEqual([files[1], files[2]])
  })
})

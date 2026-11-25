import {readFileSync} from 'fs'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {ChangeStatus, Filter, Paths, POLICY_PATH, bindChannels, loadPolicy, policyDigest, serializePolicy} from '../src/shared-image'

const destination = {repository: 'posthog-temporal-workers/data-warehouse-metadata'}
const source = 'posthog-cloud'
const fixture = readFileSync(path.join(__dirname, '../../paths-filter/__tests__/fixtures/shared-image-policy.yaml'), 'utf8')
const literal = JSON.parse(readFileSync(path.join(__dirname, 'fixtures/shared-image-fingerprints.json'), 'utf8')) as
  {paths: Paths; bytes: string; sha256: string}[]
describe('shared-image publication bindings and fingerprints', () => {
  test('binds every channel of the committed policy', () => {
    const repositoryRoot = path.join(__dirname, '../../../..')
    const policy = loadPolicy(readFileSync(path.join(repositoryRoot, POLICY_PATH), 'utf8'))
    const channels = policy.images['posthog-cloud'].channels
    const bindings = bindChannels(policy, 'posthog-cloud')['posthog-cloud']
    expect(Object.keys(bindings).sort()).toEqual(Object.keys(channels).sort())
    const base = policy.filters.sharedWorkerBase
    const witnesses = [
      '.dockerignore', 'Dockerfile', 'uv.lock',
      'tools/hogli/pyproject.toml', 'packages/owners-yaml/pyproject.toml', 'packages/owners-yaml/README.md',
      'packages/personhog-proto/pyproject.toml',
      'posthog/management/commands/migrate.py', 'posthog/management/commands/migrate_clickhouse.py',
      'posthog/migrations/0001_initial.py', 'posthog/clickhouse/migrations/0001_initial.py',
      'products/access_control/backend/migrations/0001_initial.py'
    ]
    const files = witnesses.map(filename => ({filename, status: ChangeStatus.Modified}))
    for (const [name, channel] of Object.entries(channels)) {
      expect(bindings[name]).toEqual({repository: channel.repository})
      expect({[channel.filter]: policy.filters[channel.filter].slice(0, base.length)}).toEqual({[channel.filter]: base})
      const matched = new Filter(JSON.stringify({channel: policy.filters[channel.filter]})).match(files).channel
      expect({[channel.filter]: matched.map(file => file.filename)}).toEqual({[channel.filter]: witnesses})
    }

    const workflowPath = '.github/workflows/container-images-cd.yml'
    const workflow = yaml.load(readFileSync(path.join(repositoryRoot, workflowPath), 'utf8')) as
      {jobs: {shared_image_channels: {'timeout-minutes'?: number; steps: {'timeout-minutes'?: number; with?: Record<string, string>}[]}}}
    const job = workflow.jobs.shared_image_channels
    const budgetInput = 'shared-image-budgets'
    const publish = job.steps.find(step => step.with?.[budgetInput] !== undefined)
    const budget = publish?.with?.[budgetInput]
    if (publish === undefined || budget === undefined) throw new Error(`Missing ${budgetInput} in shared_image_channels`)
    const {maxChannels, concurrency, fetchMs, comparisonMs, channelMs, totalMs} = JSON.parse(budget) as Record<string, number>
    const channelCount = Object.keys(bindings).length
    expect(channelCount).toBeLessThanOrEqual(maxChannels)
    const worstCaseMs = fetchMs + 2 * comparisonMs + Math.ceil(channelCount / concurrency) * channelMs
    if (!(worstCaseMs <= totalMs)) {
      throw new Error(`${channelCount} channels that all publish can take ${worstCaseMs} ms (fetchMs + 2 x comparisonMs + ceil(channels / concurrency) x channelMs), ` +
        `above totalMs ${totalMs}: in ${workflowPath} raise totalMs to at least ${worstCaseMs} and the publish step and job timeout-minutes with it`)
    }
    const stepMinutes = publish['timeout-minutes'] ?? 0
    if (!(stepMinutes * 60000 > totalMs)) {
      throw new Error(`In ${workflowPath} the publish step timeout-minutes ${stepMinutes} (${stepMinutes * 60000} ms) must exceed totalMs ${totalMs}`)
    }
    const stepsMinutes = job.steps.reduce((sum, step) => sum + (step['timeout-minutes'] ?? 0), 0)
    if ((job['timeout-minutes'] ?? 0) <= stepsMinutes) {
      throw new Error(`In ${workflowPath} the shared_image_channels timeout-minutes ${job['timeout-minutes']} must exceed the sum of its steps' timeout-minutes, ${stepsMinutes}`)
    }
  })

  test.each([
    ['unknown build', fixture.replace('posthog-cloud:', 'unknown-image:'), 'images.unknown-image: unknown build input'],
    ['prototype build', fixture.replace('posthog-cloud:', '__proto__:'), 'images.__proto__: unknown build input'],
    ['duplicate channel', fixture + '\n      another:\n        repository: posthog-temporal-workers/data-warehouse-metadata\n        filter: metadataAlias\n', 'conflicting destination'],
    ['source destination', fixture.replace(destination.repository, source), 'destination conflicts with source build repository'],
    ...['UPPER/image', 'registry.example.com/image:tag', '/image', 'image/', 'a', 'a'.repeat(257), 'image///name', 'image@digest', 'image___name'].map(repository =>
      [repository, fixture.replace(destination.repository, repository), 'invalid ECR repository path'])
  ])('rejects %s offline', (_name, text, message) => {
    const authored = yaml.load(text) as {images: Record<string, unknown>}
    expect(Object.keys(authored.images)).toHaveLength(1)
    expect(() => bindChannels(loadPolicy(text), source)).toThrow(message)
  })

  test.each(['dw-metadata', '__proto__'])('preserves authored channel key %s', name => {
    const policy = loadPolicy(fixture)
    policy.images[source].channels = Object.fromEntries([[name, policy.images[source].channels['dw-metadata']]])
    const resolved = bindChannels(policy, source)
    expect(Object.keys(resolved[source])).toEqual([name])
    expect(Object.prototype.hasOwnProperty.call(resolved[source], name)).toBe(true)
    expect(resolved[source][name]).toEqual(destination)
  })

  test.each(['workers/name_part', 'workers/name-part', 'workers/name.part'])('accepts ECR repository %s without a map', repository => {
    expect(bindChannels(loadPolicy(fixture.replace(destination.repository, repository)), source)).toEqual({
      [source]: {'dw-metadata': {repository}}
    })
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

})

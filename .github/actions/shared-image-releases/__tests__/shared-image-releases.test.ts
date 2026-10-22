import {readFileSync} from 'fs'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {Paths, bindChannels, loadPolicy, policyDigest, serializePolicy} from '../src/shared-image'

const destination = {repository: 'posthog-temporal-workers/data-warehouse-metadata'}
const source = 'posthog-cloud'
const fixture = readFileSync(path.join(__dirname, '../../paths-filter/__tests__/fixtures/shared-image-policy.yaml'), 'utf8')
const literal = JSON.parse(readFileSync(path.join(__dirname, 'fixtures/shared-image-fingerprints.json'), 'utf8')) as
  {paths: Paths; bytes: string; sha256: string}[]
describe('shared-image publication bindings and fingerprints', () => {
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

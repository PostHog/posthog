import {readFileSync} from 'fs'
import * as path from 'path'
import * as yaml from 'js-yaml'
import {CANONICAL_SOURCE_REPOSITORY, DestinationBinding, Paths, bindChannels, loadPolicy, policyDigest, serializePolicy} from '../src/shared-image'

const destination: DestinationBinding = {
  owner: 'metadata', repository: 'posthog-temporal-workers/data-warehouse-metadata',
  registry: '123456789012.dkr.ecr.us-east-1.amazonaws.com',
  replicas: ['123456789012.dkr.ecr.eu-central-1.amazonaws.com']
}
const source = {
  sourceRepository: CANONICAL_SOURCE_REPOSITORY, registry: destination.registry, repository: 'posthog-cloud', destinations: [destination]
}
const approved = {'posthog-cloud': source}
const fixture = readFileSync(path.join(__dirname, '../../paths-filter/__tests__/fixtures/shared-image-policy.yaml'), 'utf8')
const literal = JSON.parse(readFileSync(path.join(__dirname, 'fixtures/shared-image-fingerprints.json'), 'utf8')) as
  {paths: Paths; bytes: string; sha256: string}[]
describe('shared-image publication bindings and fingerprints', () => {
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
    expect(() => bindChannels(policy, approved)).toThrow(message)
  })

  test.each(['dw-metadata', '__proto__'])('enumerates explicitly approved prototype image and %s channel keys', name => {
    const policy = loadPolicy(fixture.replace('posthog-cloud:', '__proto__:'))
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
  })

  test('rejects independent channels whose regional replicas collide', () => {
    const document = yaml.load(fixture) as {images: Record<string, {channels: Record<string, {repository: string; filter: string}>}>}
    document.images.other = {channels: {other: {repository: destination.repository, filter: 'metadataAlias'}}}
    const other = {...source, registry: 'other-source.example.com', destinations: [{...destination, registry: 'other-origin.example.com'}]}
    expect(() => bindChannels(loadPolicy(yaml.dump(document)), {...approved, other})).toThrow(
      `images.other.channels.other: conflicting destination ${destination.replicas[0]}/${destination.repository}`
    )
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

  test('resolves the approved destination among other repositories', () => {
    const destinations = [{...destination, repository: 'other/image'}, destination]
    expect(bindChannels(loadPolicy(fixture), {'posthog-cloud': {...source, destinations}})).toEqual({
      'posthog-cloud': {'dw-metadata': destination}
    })
  })

  test('rejects conflicting independent owners in approved destination configuration', () => {
    const conflicting = {...source, destinations: [destination, {...destination, owner: 'other'}]}
    expect(() => bindChannels(loadPolicy(fixture), {'posthog-cloud': conflicting})).toThrow(/one approved destination binding/)
  })
})

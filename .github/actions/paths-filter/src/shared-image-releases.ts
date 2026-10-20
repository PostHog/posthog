import {createHash} from 'crypto'
import * as yaml from 'js-yaml'
import {Filter} from './filter'
import {ChangeStatus} from './file'

export const CANONICAL_SOURCE_REPOSITORY = 'PostHog/posthog'

export type Paths = (string | {[status: string]: string | string[]})[]
export interface Channel {
  repository: string
  filter: string
  bootstrapPolicyDigest?: string
}
export interface Policy {
  version: 1
  filters: {[name: string]: Paths}
  images: {[image: string]: {channels: {[channel: string]: Channel}}}
}
export interface DestinationBinding {
  owner: string
  repository: string
  registry: string
  replicas: readonly string[]
}
export interface ImageBinding {
  sourceRepository: string
  registry: string
  repository: string
  destinations: readonly DestinationBinding[]
}
export type ApprovedImages = {[image: string]: ImageBinding}

function object(value: unknown, location: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(`${location}: expected a mapping`)
  }
  return value as Record<string, unknown>
}

function shape(value: Record<string, unknown>, required: string[], optional: string[], location: string): void {
  const missing = required.find(key => !Object.prototype.hasOwnProperty.call(value, key))
  if (missing !== undefined) {
    throw new Error(`${location}: missing required field '${missing}'`)
  }
  const unknown = Object.keys(value).find(key => !required.includes(key) && !optional.includes(key))
  if (unknown !== undefined) {
    throw new Error(`${location}: unknown field '${unknown}'`)
  }
}

function paths(value: unknown, location: string): Paths {
  if (!Array.isArray(value) || value.length === 0) {
    throw new Error(`${location}: expected a nonempty path list`)
  }
  const resolved = value.flat(Infinity) as unknown[]
  for (const entry of resolved) {
    if (typeof entry === 'string') continue
    const statuses = object(entry, location)
    for (const pattern of Object.values(statuses)) {
      if (typeof pattern !== 'string' && !(Array.isArray(pattern) && pattern.every(p => typeof p === 'string'))) {
        throw new Error(`${location}: expected string or string array`)
      }
    }
  }
  return resolved as Paths
}

function validateChannelPaths(entries: Paths, location: string): void {
  const statuses = new Set<string>([ChangeStatus.Added, ChangeStatus.Modified, ChangeStatus.Deleted])
  for (const entry of entries) {
    if (typeof entry === 'string') {
      if (!entry.trim()) throw new Error(`${location}: empty pattern`)
      continue
    }
    if (!Object.keys(entry).length) throw new Error(`${location}: empty status mapping`)
    for (const [qualifier, value] of Object.entries(entry)) {
      if (qualifier.split('|').some(status => !statuses.has(status.trim().toLowerCase()))) {
        throw new Error(`${location}: unsupported or empty status qualifier '${qualifier}'`)
      }
      const patterns = typeof value === 'string' ? [value] : value
      if (!patterns.length || patterns.some(pattern => !pattern.trim())) {
        throw new Error(`${location}: empty status patterns`)
      }
    }
  }
  const matcher = new Filter(yaml.dump({channel: entries}))
  if (!matcher.rules.channel.some(rule => !rule.negated)) {
    throw new Error(`${location}: channel requires a positive pattern`)
  }
}

export function loadPolicy(text: string): Policy {
  const root = object(yaml.load(text), 'policy')
  shape(root, ['version', 'filters', 'images'], [], 'policy')
  if (root.version !== 1) throw new Error('policy.version: expected 1')
  const filters = Object.fromEntries(
    Object.entries(object(root.filters, 'filters')).map(([name, value]) => [name, paths(value, `filters.${name}`)])
  )
  new Filter(yaml.dump(filters))
  const images: Policy['images'] = {}
  for (const [image, value] of Object.entries(object(root.images, 'images'))) {
    const definition = object(value, `images.${image}`)
    shape(definition, ['channels'], [], `images.${image}`)
    const channels: {[name: string]: Channel} = {}
    for (const [name, channelValue] of Object.entries(object(definition.channels, `images.${image}.channels`))) {
      const location = `images.${image}.channels.${name}`
      if (!/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(name)) throw new Error(`${location}: invalid channel key`)
      const channel = object(channelValue, location)
      shape(channel, ['repository', 'filter'], ['bootstrapPolicyDigest'], location)
      if (
        typeof channel.repository !== 'string' ||
        channel.repository.length < 2 || channel.repository.length > 256 ||
        !/^(?:[a-z0-9]+(?:[._-][a-z0-9]+)*\/)*[a-z0-9]+(?:[._-][a-z0-9]+)*$/.test(channel.repository)
      ) throw new Error(`${location}.repository: invalid ECR repository path`)
      if (typeof channel.filter !== 'string' || !Object.prototype.hasOwnProperty.call(filters, channel.filter)) {
        throw new Error(`${location}.filter: unknown filter`)
      }
      if (channel.bootstrapPolicyDigest !== undefined &&
          (typeof channel.bootstrapPolicyDigest !== 'string' || !/^[0-9a-f]{64}$/.test(channel.bootstrapPolicyDigest))) {
        throw new Error(`${location}.bootstrapPolicyDigest: expected lowercase SHA-256`)
      }
      validateChannelPaths(filters[channel.filter], `filters.${channel.filter}`)
      channels[name] = channel as unknown as Channel
    }
    images[image] = {channels}
  }
  return {version: 1, filters, images}
}

export function bindChannels(policy: Policy, approved: ApprovedImages): void {
  const destinations = new Set<string>()
  for (const [image, definition] of Object.entries(policy.images)) {
    if (!Object.prototype.hasOwnProperty.call(approved, image)) throw new Error(`images.${image}: unknown build input`)
    const source = approved[image]
    for (const [name, channel] of Object.entries(definition.channels)) {
      const location = `images.${image}.channels.${name}`
      if (!source.registry || !source.repository || source.sourceRepository !== CANONICAL_SOURCE_REPOSITORY) {
        throw new Error(`${location}: source build has no approved canonical identity and coordinates`)
      }
      const bindings = source.destinations.filter(destination => destination.repository === channel.repository)
      if (bindings.length !== 1) throw new Error(`${location}.repository: expected one approved destination binding`)
      const binding = bindings[0]
      if (!binding || !binding.registry || !binding.owner) {
        throw new Error(`${location}.repository: destination has no approved owner, registry and replicas`)
      }
      for (const coordinate of [binding.registry, ...binding.replicas]) {
        const key = `${coordinate}/${channel.repository}`
        if (key === `${source.registry}/${source.repository}`) throw new Error(`${location}: destination conflicts with source build repository`)
        if (destinations.has(key)) throw new Error(`${location}: conflicting destination ${key}`)
        destinations.add(key)
      }
    }
  }
}

export function projectLegacyFilters(policy: Policy, inlineYaml: string): string {
  const inline = object(yaml.load(inlineYaml), 'legacy filters')
  const merged = {...inline}
  for (const name of Object.keys(policy.filters)) {
    if (Object.prototype.hasOwnProperty.call(inline, name) && inline[name] !== null) {
      throw new Error(`legacy filters.${name}: duplicate policy`)
    }
    merged[name] = policy.filters[name]
  }
  if (Object.values(merged).some(value => value === null)) throw new Error('legacy filters: unresolved policy reference')
  return yaml.dump(merged)
}

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value !== null && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical((value as Record<string, unknown>)[key])]))
  }
  return value
}

export function serializePolicy(entries: Paths): string {
  return JSON.stringify(canonical({paths: entries, version: 1}))
}

export function policyDigest(entries: Paths): string {
  return createHash('sha256').update(serializePolicy(entries), 'utf8').digest('hex')
}

export interface ConsumerBinding {
  owner: string
  implementation: string
  sourceRepository: string
  sourceImage: string
  logicalImageGroups: number
  repositories: readonly string[]
  inheritedGitFilters: readonly string[]
}

export function validateConsumerBinding(consumer: ConsumerBinding, source: ImageBinding, destination: DestinationBinding): void {
  const expected = [destination.registry, ...destination.replicas].map(registry => `${registry}/${destination.repository}`).sort()
  const checks: [string, boolean][] = [
    ['sourceRepository', source.sourceRepository === CANONICAL_SOURCE_REPOSITORY && consumer.sourceRepository === source.sourceRepository],
    ['implementation', consumer.implementation === 'ordered-image-v2'],
    ['logicalImageGroups', consumer.logicalImageGroups === 1],
    ['owner', consumer.owner === destination.owner],
    ['sourceImage', consumer.sourceImage === `${source.registry}/${source.repository}`],
    ['destination', source.destinations.some(approved =>
      approved.owner === destination.owner && approved.registry === destination.registry &&
      approved.repository === destination.repository &&
      JSON.stringify([...approved.replicas].sort()) === JSON.stringify([...destination.replicas].sort())
    )],
    ['repositories', JSON.stringify([...consumer.repositories].sort()) === JSON.stringify(expected)]
  ]
  for (const [field, valid] of checks) {
    if (!valid) throw new Error(`${consumer.owner}.${field}: unsupported source/consumer binding`)
  }
  if (consumer.inheritedGitFilters.length) {
    throw new Error(`${consumer.owner}: conflicting inherited Git filters: ${consumer.inheritedGitFilters.join(', ')}`)
  }
}

import * as yaml from 'js-yaml'
import {Filter} from './filter'
import {ChangeStatus} from './file'

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

function validatedMatcherYaml(filters: Record<string, unknown>): string {
  const serialized = yaml.dump(filters)
  const authored = Object.keys(filters)
  const represented = Object.keys(new Filter(serialized).rules)
  const missing = authored.find(name => !represented.includes(name))
  if (missing !== undefined || represented.length !== authored.length) {
    const name = missing ?? represented.find(name => !authored.includes(name))
    throw new Error(`filters.${name}: not representable by the matcher`)
  }
  return serialized
}

export function loadPolicy(text: string): Policy {
  const root = object(yaml.load(text), 'policy')
  shape(root, ['version', 'filters', 'images'], [], 'policy')
  if (root.version !== 1) throw new Error('policy.version: expected 1')
  const filters = Object.fromEntries(
    Object.entries(object(root.filters, 'filters')).map(([name, value]) => [name, paths(value, `filters.${name}`)])
  )
  validatedMatcherYaml(filters)
  const images: Policy['images'] = Object.create(null)
  for (const [image, value] of Object.entries(object(root.images, 'images'))) {
    const definition = object(value, `images.${image}`)
    shape(definition, ['channels'], [], `images.${image}`)
    const channels: {[name: string]: Channel} = Object.create(null)
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

export function projectLegacyFilters(policy: Policy, inlineYaml: string): string {
  const inline = object(yaml.load(inlineYaml), 'legacy filters')
  const merged: Record<string, unknown> = Object.assign(Object.create(null), inline)
  for (const name of Object.keys(policy.filters)) {
    if (Object.prototype.hasOwnProperty.call(inline, name) && inline[name] !== null) {
      throw new Error(`legacy filters.${name}: duplicate policy`)
    }
    merged[name] = policy.filters[name]
  }
  if (Object.values(merged).some(value => value === null)) throw new Error('legacy filters: unresolved policy reference')
  return validatedMatcherYaml(merged)
}

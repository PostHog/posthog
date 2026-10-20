import {createHash} from 'crypto'
import {Paths, Policy} from '../../paths-filter/src/shared-image-policy'

export const CANONICAL_SOURCE_REPOSITORY = 'PostHog/posthog'
export const POLICY_PATH = '.github/shared-image-releases.yaml'
export const ORDERED_ALIAS = /^r([0-9]{12})-([0-9a-f]{6})$/
export const REVISION = /^[0-9a-f]{40}$/
export const DIGEST = /^sha256:[0-9a-f]{64}$/

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
export type ChannelBindings = {[image: string]: {[channel: string]: DestinationBinding}}

export function approvedImages(image: string, registry: string, destinationRegistry: string, destinationsText: string): ApprovedImages {
  const destinations: unknown = JSON.parse(destinationsText || '[]')
  if (!Array.isArray(destinations)) throw new Error('Approved destinations must be an infrastructure-configured array')
  const resolved = destinations.map((value: unknown): DestinationBinding => {
    const binding = value as DestinationBinding
    if (!binding || Object.keys(binding).sort().join(',') !== 'owner,registry,replicas,repository' ||
        typeof binding.owner !== 'string' || !binding.owner || typeof binding.repository !== 'string' || !binding.repository ||
        binding.registry !== destinationRegistry ||
        !Array.isArray(binding.replicas) || binding.replicas.some(replica => typeof replica !== 'string' || !replica)) {
      throw new Error(`Invalid approved destination: ${JSON.stringify(value)}`)
    }
    return binding
  })
  return {[image]: {sourceRepository: CANONICAL_SOURCE_REPOSITORY, registry, repository: image, destinations: resolved}}
}

export function bindChannels(policy: Policy, approved: ApprovedImages): ChannelBindings {
  const destinations = new Set<string>()
  const resolved: ChannelBindings = Object.create(null)
  for (const [image, definition] of Object.entries(policy.images)) {
    if (!Object.prototype.hasOwnProperty.call(approved, image)) throw new Error(`images.${image}: unknown build input`)
    const source = approved[image]
    resolved[image] = Object.create(null)
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
      resolved[image][name] = binding
    }
  }
  return resolved
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

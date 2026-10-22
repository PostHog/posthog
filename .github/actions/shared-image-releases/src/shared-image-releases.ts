import {createHash} from 'crypto'
import {Paths, Policy} from '../../paths-filter/src/shared-image-policy'

export const CANONICAL_SOURCE_REPOSITORY = 'PostHog/posthog'

export interface DestinationBinding {
  repository: string
}
export interface ImageBinding extends DestinationBinding {
  registry: string
}
export type ChannelBindings = {[image: string]: {[channel: string]: DestinationBinding}}

export function bindChannels(policy: Policy, sourceRepository: string): ChannelBindings {
  const destinations = new Set<string>()
  const resolved: ChannelBindings = Object.create(null)
  for (const [image, definition] of Object.entries(policy.images)) {
    if (image !== sourceRepository) throw new Error(`images.${image}: unknown build input`)
    resolved[image] = Object.create(null)
    for (const [name, channel] of Object.entries(definition.channels)) {
      const location = `images.${image}.channels.${name}`
      if (channel.repository === sourceRepository) throw new Error(`${location}: destination conflicts with source build repository`)
      if (destinations.has(channel.repository)) throw new Error(`${location}: conflicting destination ${channel.repository}`)
      destinations.add(channel.repository)
      resolved[image][name] = {repository: channel.repository}
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

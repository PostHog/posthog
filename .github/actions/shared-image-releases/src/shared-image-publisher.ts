import {mkdirSync, writeFileSync} from 'fs'
import * as path from 'path'
import {SourceHistory, HistoryBudgets} from './shared-image-history'
import {ReleaseRegistry, RegistryBudgets, Outcome, Publication} from './shared-image-registry'
import {
  bindChannels, CANONICAL_SOURCE_REPOSITORY, Channel,
  Filter, ImageBinding, Policy, policyDigest, ORDERED_ALIAS, DIGEST, REVISION
} from './shared-image'

export interface PublisherBudgets extends Omit<HistoryBudgets, 'retryDelaysMs'>, RegistryBudgets {
  retryDelaysMs?: number[]
  maxChannels: number
  concurrency: number
  totalMs: number
  channelMs: number
}
export interface Bootstrap {
  channel: string
  revision: string
  digest: string
}
export interface PublisherOptions {
  cwd: string
  revision: string
  digest: string
  alias: string
  repository: string
  registry: string
  force: string[]
  bootstrap?: Bootstrap
  budgets: PublisherBudgets
  regctl: string
  helper: string
  evidence: string
  policyPath?: string
}
export interface ChannelResult {
  channel: string
  decision: 'published' | 'unchanged' | 'older-revision' | 'blocked' | 'present'
  outcome?: Outcome
  reason?: string
  tag?: string
  digest?: string
}

export function channelKeys(policy: Policy): string[] {
  return Object.entries(policy.images).flatMap(([image, definition]) => Object.keys(definition.channels).map(channel => `${image}/${channel}`))
}

export function validateRequests(policy: Policy, force: unknown, bootstrap: unknown): {force: string[]; bootstrap?: Bootstrap} {
  const keys = channelKeys(policy)
  if (!Array.isArray(force) || force.some(key => typeof key !== 'string' || !keys.includes(key))) {
    throw new Error(`Force requires explicit configured channel keys: ${JSON.stringify(force)}`)
  }
  if (bootstrap === undefined) return {force}
  const seed = bootstrap as Bootstrap
  if (!seed || typeof seed !== 'object' || Object.keys(seed).sort().join(',') !== 'channel,digest,revision' ||
      !keys.includes(seed.channel) || !REVISION.test(seed.revision) || !DIGEST.test(seed.digest) || force.length) {
    throw new Error('Bootstrap requires one configured channel, full seed revision and digest, without force')
  }
  return {force, bootstrap: seed}
}

function selectedPolicy(policy: Policy | undefined, image: string, name: string, current: Channel): string | undefined {
  const channel = policy?.images[image]?.channels[name]
  if (!channel || !policy) return undefined
  if (channel.bootstrapPolicyDigest !== undefined && channel.bootstrapPolicyDigest !== current.bootstrapPolicyDigest) {
    throw new Error(`${image}/${name}: bootstrapPolicyDigest cannot change after adoption`)
  }
  if (channel.repository !== current.repository) throw new Error(`${image}/${name}: historical destination changed`)
  return policyDigest(policy.filters[channel.filter])
}

function policyChanged(policies: (Policy | undefined)[], image: string, name: string, channel: Channel): boolean {
  let seen = false
  const digests = policies.map(policy => {
    const digest = selectedPolicy(policy, image, name, channel)
    if (digest) seen = true
    if (!seen) {
      if (!channel.bootstrapPolicyDigest) throw new Error(`${image}/${name}: missing bootstrapPolicyDigest for historical policy gap`)
      return channel.bootstrapPolicyDigest
    }
    return digest
  })
  return digests.some(digest => digest !== digests[0])
}

interface ResolvedChannel {
  image: string
  name: string
  key: string
  channel: Channel
  destination: ImageBinding
  source: ImageBinding
}

interface ChannelContext {
  options: PublisherOptions
  policy: Policy
  history: SourceHistory
}

async function bootstrapChannel(selected: ResolvedChannel, seed: Bootstrap, context: ChannelContext, registry: ReleaseRegistry): Promise<ChannelResult> {
  const {image, name, key, channel, destination, source} = selected
  const {options, policy, history} = context
  const inventory = await registry.list(destination)
  const tag = await history.alias(seed.revision)
  if (await history.relation(seed.revision, options.revision) === 'older') throw new Error(`${key}: seed is newer than the executing revision`)
  const seedPolicy = await history.policyAt(seed.revision)
  const seedPolicyDigest = selectedPolicy(seedPolicy, image, name, channel)
  const existing = inventory.nonempty ? await registry.read(destination, tag, seed.digest) : undefined
  if (existing && existing.outcome !== 'present-at-expected-digest') {
    throw new Error(`${key}: ${existing.outcome === 'integrity-mismatch' ? 'seed digest conflict' : existing.outcome === 'absent' ? 'seed missing in nonempty destination' : `seed readback unavailable: ${existing.reason ?? 'unknown'}`}`)
  }
  if (!existing && seedPolicyDigest === undefined &&
      channel.bootstrapPolicyDigest !== policyDigest(policy.filters[channel.filter])) {
    throw new Error(`${key}: bootstrapPolicyDigest must match the reviewed current policy`)
  }
  await verifyImage(registry, existing ? destination : source, seed.digest, seed.revision)
  const publicationResult = existing ?? await registry.publish(source, destination, seed.digest, tag)
  if (publicationResult.outcome === 'present-at-expected-digest') {
    const receipt = {
      version: 1, sourceRepository: CANONICAL_SOURCE_REPOSITORY, sourceImage: `${source.registry}/${source.repository}`,
      destination, policyRevision: options.revision, policyDigest: policyDigest(policy.filters[channel.filter]),
      seedRevision: seed.revision, ordinal: Number(tag.slice(1, 13)), tag, digest: seed.digest, outcome: publicationResult.outcome
    }
    const file = path.join(options.evidence, 'bootstrap', image, `${name}.json`)
    mkdirSync(path.dirname(file), {recursive: true})
    writeFileSync(file, JSON.stringify(receipt, null, 2) + '\n')
  }
  return publication(key, publicationResult, tag, seed.digest, Boolean(existing))
}

async function advanceChannel(selected: ResolvedChannel, force: string[], context: ChannelContext, registry: ReleaseRegistry): Promise<ChannelResult> {
  const {image, name, key, channel, destination, source} = selected
  const {options, policy, history} = context
  const inventory = await registry.list(destination)
  const frontier = [...inventory.tags].filter(tag => ORDERED_ALIAS.test(tag)).sort().pop()
  if (!frontier) throw new Error(`${key}: empty ordered frontier requires explicit bootstrap`)
  const readback = await registry.read(destination, frontier, options.digest)
  if (readback.outcome === 'unknown') throw new Error(`${key}: frontier readback unavailable: ${readback.reason ?? 'unknown'}`)
  const digest = readback.digest
  if (!digest) throw new Error(`${key}: frontier disappeared during readback`)
  const identity = await registry.identity(destination.registry, destination.repository, digest)
  if (await history.alias(identity.revision) !== frontier) throw new Error(`${key}: frontier ordinal mismatch`)
  const relation = await history.relation(identity.revision, options.revision)
  if (relation === 'older') return {channel: key, decision: 'older-revision'}
  if (relation === 'equal') {
    return publication(key, readback, frontier, options.digest, true)
  }
  const comparison = await history.compare(identity.revision, options.revision)
  const changed = policyChanged(comparison.policies, image, name, channel)
  const matches = new Filter(JSON.stringify({channel: policy.filters[channel.filter]})).match(comparison.files).channel.length > 0
  if (!changed && !matches && !force.includes(key)) return {channel: key, decision: 'unchanged'}
  await verifyImage(registry, source, options.digest, options.revision)
  return publication(key, await registry.publish(source, destination, options.digest, options.alias), options.alias, options.digest)
}

export async function publishChannels(options: PublisherOptions): Promise<ChannelResult[]> {
  if (!/^[0-9]{12}\.dkr\.ecr\.[a-z]{2}(?:-[a-z]+)+-[0-9]+\.amazonaws\.com$/.test(options.registry)) throw new Error('Invalid authenticated ECR registry hostname')
  const {budgets} = options
  for (const name of ['fetchMs', 'comparisonMs', 'maxBuffer', 'registryMs', 'copySeconds', 'readbackSeconds', 'maxChannels', 'concurrency', 'totalMs', 'channelMs'] as const) {
    const value = budgets[name]
    if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`Invalid publisher budget: ${name}`)
  }
  const retryDelaysMs = budgets.retryDelaysMs === undefined ? [5000, 15000] : budgets.retryDelaysMs
  if (!Array.isArray(retryDelaysMs) || retryDelaysMs.length !== 2 || !retryDelaysMs.every(delay => Number.isSafeInteger(delay) && delay >= 0)) {
    throw new Error('Invalid publisher budget: retryDelaysMs')
  }
  const deadline = Date.now() + budgets.totalMs
  const history = new SourceHistory(options.cwd, {...budgets, retryDelaysMs: [retryDelaysMs[0], retryDelaysMs[1]]}, deadline, options.policyPath)
  await history.verify(options.revision)
  if (await history.alias(options.revision) !== options.alias) throw new Error('Built ordered alias differs from verified source history')
  if (!DIGEST.test(options.digest)) throw new Error('Expected successful build digest')
  const policy = await history.current(options.revision)
  const requests = validateRequests(policy, options.force, options.bootstrap)
  const bindings = bindChannels(policy, options.repository)
  const channels = Object.entries(policy.images).flatMap(([image, definition]) =>
    Object.entries(definition.channels).map(([name, channel]) => ({image, name, channel, key: `${image}/${name}`, destination: {...bindings[image][name], registry: options.registry}, source: {repository: options.repository, registry: options.registry}}))
  )
  if (channels.length > budgets.maxChannels) throw new Error(`Channel fan-out ${channels.length} exceeds budget ${budgets.maxChannels}`)
  const selected = requests.bootstrap ? channels.filter(channel => channel.key === requests.bootstrap?.channel) : channels
  const results: ChannelResult[] = []
  const context = {options, policy, history}
  let next = 0
  const worker = async (): Promise<void> => {
    while (next < selected.length) {
      const channel = selected[next++]
      let result: ChannelResult
      try {
        const registry = new ReleaseRegistry(options.cwd, options.regctl, options.helper, budgets, Math.min(deadline, Date.now() + budgets.channelMs))
        result = requests.bootstrap
          ? await bootstrapChannel(channel, requests.bootstrap, context, registry)
          : await advanceChannel(channel, requests.force, context, registry)
      } catch (error) {
        result = {channel: channel.key, decision: 'blocked', reason: `${channel.key}: ${String(error)}`}
      }
      results.push(result)
      process.stdout.write(JSON.stringify(result) + '\n')
    }
  }
  await Promise.all(Array.from({length: Math.min(budgets.concurrency, selected.length)}, worker))
  mkdirSync(options.evidence, {recursive: true})
  writeFileSync(path.join(options.evidence, 'results.json'), JSON.stringify(results, null, 2) + '\n')
  return results
}

async function verifyImage(registry: ReleaseRegistry, coordinate: Pick<ImageBinding, 'registry' | 'repository'>, digest: string, revision: string): Promise<void> {
  const identity = await registry.identity(coordinate.registry, coordinate.repository, digest)
  if (identity.revision !== revision) throw new Error('Image revision differs from approved source identity')
}

function publication(channel: string, result: Publication, tag: string, digest: string, present = false): ChannelResult {
  return {
    channel, decision: result.outcome === 'present-at-expected-digest' ? present ? 'present' : 'published' : 'blocked',
    outcome: result.outcome, tag, digest, ...(result.reason ? {reason: result.reason} : {})
  }
}

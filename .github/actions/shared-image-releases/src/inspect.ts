import * as core from '@actions/core'
import {readFileSync} from 'fs'
import * as path from 'path'
import {ApprovedImages, CANONICAL_SOURCE_REPOSITORY, DestinationBinding, bindChannels, loadPolicy} from './shared-image'

export function approvedImages(image: string, registry: string, destinationRegistry: string, destinationsText: string): ApprovedImages {
  const destinations: unknown = JSON.parse(destinationsText || '[]')
  if (!Array.isArray(destinations)) throw new Error('Approved destinations must be an infrastructure-configured array')
  const resolved = destinations.map((value: unknown): DestinationBinding => {
    const binding = value as DestinationBinding
    if (!binding || typeof binding !== 'object' || Object.keys(binding).sort().join(',') !== 'owner,registry,replicas,repository' ||
        typeof binding.owner !== 'string' || !binding.owner || typeof binding.repository !== 'string' || !binding.repository ||
        !destinationRegistry || binding.registry !== destinationRegistry ||
        !Array.isArray(binding.replicas) || binding.replicas.some(replica => typeof replica !== 'string' || !replica)) {
      throw new Error(`Invalid approved destination: ${JSON.stringify(value)}`)
    }
    return binding
  })
  return {[image]: {sourceRepository: CANONICAL_SOURCE_REPOSITORY, registry, repository: image, destinations: resolved}}
}

export function run(): void {
  try {
    const operation = core.getInput('shared-image-operation') || 'inspect'
    if (operation !== 'inspect') throw new Error(`Unknown shared-image operation: ${operation}`)
    const cwd = core.getInput('working-directory') || process.cwd()
    const policyPath = core.getInput('shared-image-policy') || '.github/shared-image-releases.yaml'
    const policy = loadPolicy(readFileSync(path.resolve(cwd, policyPath), 'utf8'))
    const approved = approvedImages(
      core.getInput('shared-image-repository', {required: true}),
      core.getInput('shared-image-registry', {required: true}),
      core.getInput('shared-image-destination-registry', {required: true}),
      core.getInput('shared-image-destinations')
    )
    const bindings = bindChannels(policy, approved)
    core.setOutput('channels', Object.values(bindings).some(channels => Object.keys(channels).length > 0) ? 'true' : 'false')
    core.setOutput('publication-results', JSON.stringify(bindings))
  } catch (error) {
    core.setFailed(error instanceof Error ? error.message : String(error))
  }
}

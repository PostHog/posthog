import * as core from '@actions/core'
import {readFileSync} from 'fs'
import * as path from 'path'
import {loadPolicy} from '../../paths-filter/src/shared-image-policy'
import {approvedImages, bindChannels} from './shared-image-releases'

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

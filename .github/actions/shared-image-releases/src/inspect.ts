import * as core from '@actions/core'
import {readFileSync} from 'fs'
import * as path from 'path'
import {loadPolicy} from '../../paths-filter/src/shared-image-policy'
import {bindChannels} from './shared-image-releases'

export function run(): void {
  try {
    const repository = core.getInput('shared-image-repository', {required: true})
    const operation = core.getInput('shared-image-operation') || 'inspect'
    if (operation !== 'inspect') throw new Error(`Unknown shared-image operation: ${operation}`)
    const cwd = core.getInput('working-directory') || process.cwd()
    const policyPath = core.getInput('shared-image-policy') || '.github/shared-image-releases.yaml'
    const policy = loadPolicy(readFileSync(path.resolve(cwd, policyPath), 'utf8'))
    const bindings = bindChannels(policy, repository)
    core.setOutput('channels', Object.values(bindings).some(channels => Object.keys(channels).length > 0) ? 'true' : 'false')
    core.setOutput('bindings', JSON.stringify(bindings))
  } catch (error) {
    core.setFailed(error instanceof Error ? error.message : String(error))
  }
}

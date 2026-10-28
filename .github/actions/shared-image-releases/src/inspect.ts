import {POLICY_PATH} from './shared-image-releases'
import {Bootstrap, publishChannels, PublisherBudgets} from './shared-image-publisher'
import * as core from '@actions/core'
import {readFileSync} from 'fs'
import * as path from 'path'
import {loadPolicy} from '../../paths-filter/src/shared-image-policy'
import {bindChannels} from './shared-image-releases'

interface Configuration {
  cwd: string
  policyPath: string
  repository: string
}

async function publish(config: Configuration): Promise<void> {
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH || '', 'utf8')) as {repository?: {default_branch?: string}}
  if (process.env.GITHUB_REF !== `refs/heads/${event.repository?.default_branch}`) throw new Error('Shared-image publication requires the default branch')
  const force = JSON.parse(core.getInput('shared-image-force') || '[]') as string[]
  const bootstrapText = core.getInput('shared-image-bootstrap')
  const bootstrap = bootstrapText ? JSON.parse(bootstrapText) as Bootstrap : undefined
  if ((force.length || bootstrap) && process.env.GITHUB_EVENT_NAME !== 'workflow_dispatch') {
    throw new Error('Force and bootstrap require an authorized manual default-branch invocation')
  }
  const results = await publishChannels({
    ...config, registry: core.getInput('shared-image-registry', {required: true}), revision: process.env.GITHUB_SHA || '', digest: core.getInput('shared-image-digest'),
    alias: core.getInput('shared-image-alias'), force, bootstrap,
    budgets: JSON.parse(core.getInput('shared-image-budgets')) as PublisherBudgets,
    regctl: core.getInput('shared-image-regctl'), helper: path.resolve(config.cwd, '.github/scripts/ordered-image-release.sh'),
    evidence: path.resolve(config.cwd, 'shared-image-releases')
  })
  if (results.some(result => result.decision === 'blocked')) core.setFailed('One or more shared-image channels are blocked; inspect publication evidence')
}

export async function run(): Promise<void> {
  try {
    const repository = core.getInput('shared-image-repository', {required: true})
    const operation = core.getInput('shared-image-operation') || 'inspect'
    if (operation !== 'inspect' && operation !== 'publish') throw new Error(`Unknown shared-image operation: ${operation}`)
    const cwd = core.getInput('working-directory') || process.cwd()
    const policyPath = core.getInput('shared-image-policy') || POLICY_PATH
    if (operation === 'publish') {
      await publish({cwd, policyPath, repository})
      return
    }
    const policy = loadPolicy(readFileSync(path.resolve(cwd, policyPath), 'utf8'))
    const bindings = bindChannels(policy, repository)
    core.setOutput('channels', Object.values(bindings).some(channels => Object.keys(channels).length > 0) ? 'true' : 'false')
    core.setOutput('bindings', JSON.stringify(bindings))
  } catch (error) {
    core.setFailed(error instanceof Error ? error.message : String(error))
  }
}

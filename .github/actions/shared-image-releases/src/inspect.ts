import * as core from '@actions/core'
import {readFileSync} from 'fs'
import * as path from 'path'
import {approvedImages, ApprovedImages, bindChannels, loadPolicy, POLICY_PATH} from './shared-image'
import {Bootstrap, publishChannels, PublisherBudgets} from './shared-image-publisher'

interface Configuration {
  cwd: string
  policyPath: string
  approved: ApprovedImages
}

function configuration(): Configuration {
  return {
    cwd: path.resolve(core.getInput('working-directory') || process.cwd()),
    policyPath: core.getInput('shared-image-policy') || POLICY_PATH,
    approved: approvedImages(
      core.getInput('shared-image-repository', {required: true}),
      core.getInput('shared-image-registry', {required: true}),
      core.getInput('shared-image-destination-registry', {required: true}),
      core.getInput('shared-image-destinations')
    )
  }
}

function inspect(config: Configuration): void {
  const policy = loadPolicy(readFileSync(path.resolve(config.cwd, config.policyPath), 'utf8'))
  const bindings = bindChannels(policy, config.approved)
  core.setOutput('channels', Object.values(bindings).some(channels => Object.keys(channels).length > 0) ? 'true' : 'false')
  core.setOutput('bindings', JSON.stringify(bindings))
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
    ...config, revision: process.env.GITHUB_SHA || '', digest: core.getInput('shared-image-digest'),
    alias: core.getInput('shared-image-alias'), force, bootstrap,
    budgets: JSON.parse(core.getInput('shared-image-budgets')) as PublisherBudgets,
    regctl: core.getInput('shared-image-regctl'), helper: path.resolve(config.cwd, '.github/scripts/ordered-image-release.sh'),
    evidence: path.resolve(config.cwd, 'shared-image-releases')
  })
  if (results.some(result => result.decision === 'blocked')) core.setFailed('One or more shared-image channels are blocked; inspect publication evidence')
}

export async function run(): Promise<void> {
  try {
    const operation = core.getInput('shared-image-operation') || 'inspect'
    if (operation !== 'inspect' && operation !== 'publish') throw new Error(`Unknown shared-image operation: ${operation}`)
    const config = configuration()
    if (operation === 'inspect') inspect(config)
    else await publish(config)
  } catch (error) {
    core.setFailed(error instanceof Error ? error.message : String(error))
  }
}

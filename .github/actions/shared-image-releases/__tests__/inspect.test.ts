jest.mock('../src/shared-image-command')

import * as core from '@actions/core'
import * as path from 'path'
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import {command} from '../src/shared-image-command'
import {run} from '../src/inspect'
import {POLICY_PATH} from '../src/shared-image-releases'
import * as publisher from '../src/shared-image-publisher'

jest.mock('@actions/core', () => ({getInput: jest.fn(), setOutput: jest.fn(), setFailed: jest.fn()}))

const destination = {repository: 'posthog-temporal-workers/data-warehouse-metadata'}
const inputs: Record<string, string> = {
  'working-directory': path.join(__dirname, '../../paths-filter'),
  'shared-image-policy': '__tests__/fixtures/shared-image-policy.yaml',
  'shared-image-repository': 'posthog-cloud'
}

describe('inspect action inputs and outputs', () => {
  test('requires the source repository through the Actions runtime input contract', async () => {
    const actual = jest.requireActual<typeof core>('@actions/core')
    const environment = {...process.env}
    try {
      for (const [name, value] of Object.entries(inputs)) process.env[`INPUT_${name.toUpperCase()}`] = value
      delete process.env['INPUT_SHARED-IMAGE-REPOSITORY']
      jest.mocked(core.getInput).mockImplementation(actual.getInput)
      await run()
      expect(core.setOutput).not.toHaveBeenCalled()
      expect(core.setFailed).toHaveBeenCalledWith('Input required and not supplied: shared-image-repository')
    } finally {
      process.env = environment
    }
  })

  test.each(['inspect', ''])('resolves offline bindings with operation %s', async operation => {
    jest.mocked(core.getInput).mockImplementation(name => name === 'shared-image-operation' ? operation : inputs[name] || '')
    await run()
    expect(core.setFailed).not.toHaveBeenCalled()
    expect(core.setOutput).toHaveBeenCalledWith('channels', 'true')
    expect(core.setOutput).toHaveBeenCalledWith('bindings', JSON.stringify({'posthog-cloud': {'dw-metadata': destination}}))
  })

  test('an empty configured channel set emits false and the resolved empty map', async () => {
    const scratch = mkdtempSync(path.join(tmpdir(), 'shared-image-empty-'))
    try {
      const policyFile = path.join(scratch, POLICY_PATH)
      mkdirSync(path.dirname(policyFile), {recursive: true})
      writeFileSync(policyFile, JSON.stringify({
        version: 1, filters: {}, images: {'posthog-cloud': {channels: {}}}
      }))
      jest.mocked(core.getInput).mockImplementation(name => {
        if (name === 'working-directory') return scratch
        if (name === 'shared-image-policy') return ''
        return inputs[name] || ''
      })
      await run()
      expect(core.setFailed).not.toHaveBeenCalled()
      expect(core.setOutput).toHaveBeenCalledWith('channels', 'false')
      expect(core.setOutput).toHaveBeenCalledWith('bindings', '{"posthog-cloud":{}}')
    } finally {
      rmSync(scratch, {recursive: true, force: true})
    }
  })

  test.each([
    ['shared-image-operation', 'unknown', 'Unknown shared-image operation: unknown'],
    ['shared-image-repository', 'unknown-image', 'images.posthog-cloud: unknown build input']
  ])('rejects invalid %s=%s by name without emitting bindings', async (name, value, error) => {
    jest.mocked(core.getInput).mockImplementation(key => key === name ? value : inputs[key] || '')
    await run()
    expect(core.setOutput).not.toHaveBeenCalled()
    expect(core.setFailed).toHaveBeenCalledWith(expect.stringContaining(error))
  })
})

describe('publisher input gates', () => {
  test.each([true, false])('publication step reports blocked=%s', async blocked => {
    const environment = {...process.env}
    const scratch = mkdtempSync(path.join(tmpdir(), 'shared-image-results-'))
    const publish = jest.spyOn(publisher, 'publishChannels').mockResolvedValue([
      {channel: 'posthog-cloud/worker', decision: blocked ? 'blocked' : 'published'},
      {channel: 'posthog-cloud/other', decision: 'published'}
    ])
    try {
      const event = path.join(scratch, 'event.json')
      writeFileSync(event, JSON.stringify({repository: {default_branch: 'main'}}))
      process.env.GITHUB_EVENT_PATH = event
      process.env.GITHUB_REF = 'refs/heads/main'
      process.env.GITHUB_EVENT_NAME = 'push'
      const publishInputs: Record<string, string> = {
        ...inputs, 'shared-image-operation': 'publish',
        'shared-image-registry': '123456789012.dkr.ecr.us-east-1.amazonaws.com',
        'shared-image-budgets': '{}'
      }
      jest.mocked(core.getInput).mockImplementation(name => publishInputs[name] || '')
      await run()
      expect(publish).toHaveBeenCalledTimes(1)
      if (blocked) expect(core.setFailed).toHaveBeenCalledWith('One or more shared-image channels are blocked; inspect publication evidence')
      else expect(core.setFailed).not.toHaveBeenCalled()
    } finally {
      publish.mockRestore()
      process.env = environment
      rmSync(scratch, {recursive: true, force: true})
    }
  })

  test.each([['publish', 'shared-image-registry']])('requires %s input %s through the Actions runtime input contract', async (operation, missing) => {
    const actual = jest.requireActual<typeof core>('@actions/core')
    const environment = {...process.env}
    const scratch = mkdtempSync(path.join(tmpdir(), 'shared-image-input-'))
    try {
      const event = path.join(scratch, 'event.json')
      writeFileSync(event, JSON.stringify({repository: {default_branch: 'main'}}))
      process.env.GITHUB_EVENT_PATH = event
      process.env.GITHUB_REF = 'refs/heads/main'
      process.env['INPUT_SHARED-IMAGE-OPERATION'] = operation
      process.env['INPUT_SHARED-IMAGE-FORCE'] = '[]'
      process.env['INPUT_SHARED-IMAGE-BOOTSTRAP'] = ''
      for (const [name, value] of Object.entries(inputs)) process.env[`INPUT_${name.toUpperCase()}`] = value
      delete process.env[`INPUT_${missing.toUpperCase()}`]
      jest.mocked(core.getInput).mockImplementation(actual.getInput)
      await run()
      expect(core.setOutput).not.toHaveBeenCalled()
      expect(core.setFailed).toHaveBeenCalledWith(`Input required and not supplied: ${missing}`)
    } finally {
      process.env = environment
      rmSync(scratch, {recursive: true, force: true})
    }
  })

  test('inspection does not parse publication requests', async () => {
    jest.mocked(core.getInput).mockImplementation(name => {
      if (name === 'shared-image-force' || name === 'shared-image-bootstrap') return 'invalid'
      return inputs[name] || ''
    })
    await run()
    expect(core.setFailed).not.toHaveBeenCalled()
    expect(core.setOutput).toHaveBeenCalledWith('channels', 'true')
  })

  test.each([
    ['non-default branch', 'refs/heads/feature', 'workflow_dispatch', '[]', '', 'Shared-image publication requires the default branch'],
    ['force on push', 'refs/heads/main', 'push', '["posthog-cloud/dw-metadata"]', '', 'Force and bootstrap require an authorized manual default-branch invocation'],
    ['bootstrap on push', 'refs/heads/main', 'push', '[]', JSON.stringify({channel: 'posthog-cloud/dw-metadata', revision: 'a'.repeat(40), digest: 'sha256:' + 'b'.repeat(64)}), 'Force and bootstrap require an authorized manual default-branch invocation']
  ])('rejects publish for %s before running a command', async (_name, ref, eventName, force, bootstrap, error) => {
    const environment = {...process.env}
    const scratch = mkdtempSync(path.join(tmpdir(), 'shared-image-entry-'))
    try {
      const event = path.join(scratch, 'event.json')
      writeFileSync(event, JSON.stringify({repository: {default_branch: 'main'}}))
      process.env.GITHUB_EVENT_PATH = event
      process.env.GITHUB_REF = ref
      process.env.GITHUB_EVENT_NAME = eventName
      process.env.GITHUB_SHA = 'a'.repeat(40)
      jest.mocked(command).mockClear()
      const publishInputs: Record<string, string> = {
        ...inputs, 'shared-image-operation': 'publish', 'shared-image-force': force, 'shared-image-bootstrap': bootstrap,
        'shared-image-budgets': JSON.stringify({fetchMs: 30000, comparisonMs: 30000, maxBuffer: 1024, registryMs: 30000,
          copySeconds: 1, readbackSeconds: 1, maxChannels: 1, concurrency: 1, channelMs: 60000, totalMs: 120000})
      }
      jest.mocked(core.getInput).mockImplementation(name => publishInputs[name] || '')
      await run()
      expect(command).not.toHaveBeenCalled()
      expect(core.setFailed).toHaveBeenCalledWith(error)
      expect(core.setOutput).not.toHaveBeenCalled()
    } finally {
      process.env = environment
      rmSync(scratch, {recursive: true, force: true})
    }
  })

})

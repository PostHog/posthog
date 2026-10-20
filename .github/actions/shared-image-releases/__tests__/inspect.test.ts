import * as core from '@actions/core'
import * as path from 'path'
import {mkdtempSync, rmSync, writeFileSync} from 'fs'
import {tmpdir} from 'os'
import {run} from '../src/inspect'
import {approvedImages} from '../src/shared-image'
import {command} from '../src/shared-image-command'

jest.mock('@actions/core', () => ({getInput: jest.fn(), setOutput: jest.fn(), setFailed: jest.fn()}))
jest.mock('../src/shared-image-command')

const destination = {
  owner: 'metadata', repository: 'posthog-temporal-workers/data-warehouse-metadata',
  registry: 'destination.example.com', replicas: ['replica.example.com']
}
const inputs: Record<string, string> = {
  'working-directory': path.join(__dirname, '../../paths-filter'),
  'shared-image-policy': '__tests__/fixtures/shared-image-policy.yaml',
  'shared-image-repository': 'posthog-cloud',
  'shared-image-registry': 'source.example.com',
  'shared-image-destination-registry': destination.registry,
  'shared-image-destinations': JSON.stringify([destination])
}

describe('inspect action inputs and outputs', () => {
  test.each([
    ['approved coordinates', 'another-image', [destination], {
      'another-image': {sourceRepository: 'PostHog/posthog', registry: 'source.example.com', repository: 'another-image', destinations: [destination]}
    }],
    ['another approved image', 'posthog-cloud', [destination], {
      'posthog-cloud': {sourceRepository: 'PostHog/posthog', registry: 'source.example.com', repository: 'posthog-cloud', destinations: [destination]}
    }],
    ['extra key', 'another-image', [{...destination, extra: true}], null],
    ['missing replicas', 'another-image', [{...destination, replicas: undefined}], null],
    ['string replicas', 'another-image', [{...destination, replicas: 'replica.example.com'}], null],
    ['empty replica', 'another-image', [{...destination, replicas: ['']}], null],
    ['numeric owner', 'another-image', [{...destination, owner: 7}], null],
    ['numeric repository', 'another-image', [{...destination, repository: 7}], null],
    ['numeric replica', 'another-image', [{...destination, replicas: [5]}], null],
    ['null destination', 'another-image', [null], null],
    ['null replica', 'another-image', [{...destination, replicas: [null]}], null],
    ['empty owner', 'another-image', [{...destination, owner: ''}], null],
    ['empty repository', 'another-image', [{...destination, repository: ''}], null]
  ] as const)('approved publication map: %s', (_name, image, destinations, expected) => {
    const resolve = (): ReturnType<typeof approvedImages> => approvedImages(image, 'source.example.com', destination.registry, JSON.stringify(destinations))
    if (expected === null) {
      expect(resolve).toThrow(`Invalid approved destination: ${JSON.stringify(destinations[0])}`)
    } else {
      expect(resolve()).toStrictEqual(expected)
    }
  })

  test('empty destination configuration resolves to an empty approved list', () => {
    expect(approvedImages('posthog-cloud', 'source.example.com', destination.registry, '')['posthog-cloud'].destinations).toEqual([])
  })

  test.each(['shared-image-repository', 'shared-image-registry', 'shared-image-destination-registry'])('requires %s through the Actions runtime input contract', async missing => {
    const actual = jest.requireActual<typeof core>('@actions/core')
    const environment = {...process.env}
    try {
      for (const [name, value] of Object.entries(inputs)) process.env[`INPUT_${name.toUpperCase()}`] = value
      delete process.env[`INPUT_${missing.toUpperCase()}`]
      jest.mocked(core.getInput).mockImplementation(actual.getInput)
      await run()
      expect(core.setOutput).not.toHaveBeenCalled()
      expect(core.setFailed).toHaveBeenCalledWith(`Input required and not supplied: ${missing}`)
    } finally {
      process.env = environment
    }
  })

  test.each(['inspect', ''])('resolves approved bindings with operation %s', async operation => {
    jest.mocked(core.getInput).mockImplementation(name => name === 'shared-image-operation' ? operation : inputs[name] || '')
    await run()
    expect(core.setFailed).not.toHaveBeenCalled()
    expect(core.setOutput).toHaveBeenCalledWith('channels', 'true')
    expect(core.setOutput).toHaveBeenCalledWith('bindings', JSON.stringify({'posthog-cloud': {'dw-metadata': destination}}))
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

  test('an empty configured channel set emits false and the resolved empty map', async () => {
    jest.mocked(core.getInput).mockImplementation(name => {
      if (name === 'working-directory') return path.join(__dirname, '../../../..')
      if (name === 'shared-image-policy') return ''
      return inputs[name] || ''
    })
    await run()
    expect(core.setFailed).not.toHaveBeenCalled()
    expect(core.setOutput).toHaveBeenCalledWith('channels', 'false')
    expect(core.setOutput).toHaveBeenCalledWith('bindings', '{"posthog-cloud":{}}')
  })

  test.each([
    ['shared-image-operation', 'unknown', 'Unknown shared-image operation: unknown'],
    ['shared-image-repository', 'unknown-image', 'images.posthog-cloud: unknown build input'],
    ['shared-image-destinations', '[]', 'images.posthog-cloud.channels.dw-metadata.repository: expected one approved destination binding'],
    ['shared-image-destination-registry', 'unapproved.example.com', `Invalid approved destination: ${JSON.stringify(destination)}`],
    ['shared-image-destinations', '{}', 'Approved destinations must be an infrastructure-configured array'],
    ['shared-image-destinations', 'invalid', 'Unexpected token']
  ])('rejects invalid %s=%s by name without emitting bindings', async (name, value, error) => {
    jest.mocked(core.getInput).mockImplementation(key => key === name ? value : inputs[key] || '')
    await run()
    expect(core.setOutput).not.toHaveBeenCalled()
    expect(core.setFailed).toHaveBeenCalledWith(expect.stringContaining(error))
  })
})

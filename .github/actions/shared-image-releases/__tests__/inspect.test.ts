import * as core from '@actions/core'
import * as path from 'path'
import {run} from '../src/inspect'
import {approvedImages} from '../src/shared-image'

jest.mock('@actions/core', () => ({getInput: jest.fn(), setOutput: jest.fn(), setFailed: jest.fn()}))

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

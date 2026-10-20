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

  test.each(['inspect', ''])('resolves approved bindings with operation %s', operation => {
    jest.mocked(core.getInput).mockImplementation(name => name === 'shared-image-operation' ? operation : inputs[name] || '')
    run()
    expect(core.setFailed).not.toHaveBeenCalled()
    expect(core.setOutput).toHaveBeenCalledWith('channels', 'true')
    expect(core.setOutput).toHaveBeenCalledWith('publication-results', JSON.stringify({'posthog-cloud': {'dw-metadata': destination}}))
  })

  test('an empty configured channel set emits false and the resolved empty map', () => {
    jest.mocked(core.getInput).mockImplementation(name => {
      if (name === 'working-directory') return path.join(__dirname, '../../../..')
      if (name === 'shared-image-policy') return ''
      return inputs[name] || ''
    })
    run()
    expect(core.setFailed).not.toHaveBeenCalled()
    expect(core.setOutput).toHaveBeenCalledWith('channels', 'false')
    expect(core.setOutput).toHaveBeenCalledWith('publication-results', '{"posthog-cloud":{}}')
  })

  test.each([
    ['shared-image-operation', 'publish', 'Unknown shared-image operation: publish'],
    ['shared-image-repository', 'unknown-image', 'images.posthog-cloud: unknown build input'],
    ['shared-image-destinations', '[]', 'images.posthog-cloud.channels.dw-metadata.repository: expected one approved destination binding'],
    ['shared-image-destination-registry', 'unapproved.example.com', `Invalid approved destination: ${JSON.stringify(destination)}`],
    ['shared-image-destinations', '{}', 'Approved destinations must be an infrastructure-configured array'],
    ['shared-image-destinations', 'invalid', 'Unexpected token']
  ])('rejects invalid %s=%s by name without emitting bindings', (name, value, error) => {
    jest.mocked(core.getInput).mockImplementation(key => key === name ? value : inputs[key] || '')
    run()
    expect(core.setOutput).not.toHaveBeenCalled()
    expect(core.setFailed).toHaveBeenCalledWith(expect.stringContaining(error))
  })
})

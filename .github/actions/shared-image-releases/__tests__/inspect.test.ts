import * as core from '@actions/core'
import * as path from 'path'
import {run} from '../src/inspect'

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
    ['shared-image-repository', 'unknown-image', 'images.posthog-cloud: unknown build input']
  ])('rejects invalid %s=%s by name without emitting bindings', async (name, value, error) => {
    jest.mocked(core.getInput).mockImplementation(key => key === name ? value : inputs[key] || '')
    await run()
    expect(core.setOutput).not.toHaveBeenCalled()
    expect(core.setFailed).toHaveBeenCalledWith(expect.stringContaining(error))
  })
})

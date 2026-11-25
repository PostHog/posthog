import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { pipelinePluginConfigurationLogic } from './pipelinePluginConfigurationLogic'

describe('pipelinePluginConfigurationLogic', () => {
    let captureException: jest.SpyInstance

    beforeEach(() => {
        captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
    })

    afterEach(() => {
        captureException.mockRestore()
    })

    it.each([
        { status: 404, reported: false },
        { status: 500, reported: true },
    ])('a $status loading the plugin config is reported: $reported', async ({ status, reported }) => {
        useMocks({
            get: { '/api/projects/:team_id/plugin_configs/:id': () => [status, { detail: 'Not found.' }] },
        })
        initKeaTests()
        const logic = pipelinePluginConfigurationLogic({ pluginId: null, pluginConfigId: 1 })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPluginConfigFailure']).toMatchValues({ plugin: null })

        expect(captureException).toHaveBeenCalledTimes(reported ? 1 : 0)
    })
})

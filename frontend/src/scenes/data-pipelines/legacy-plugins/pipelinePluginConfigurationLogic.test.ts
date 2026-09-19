import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { initKeaTests } from '~/test/init'

import { pipelinePluginConfigurationLogic } from './pipelinePluginConfigurationLogic'

jest.mock('lib/api', () => ({
    ...jest.requireActual('lib/api'),
    pluginConfigs: {
        get: jest.fn(),
    },
}))

const mockApi = api.pluginConfigs as jest.Mocked<typeof api.pluginConfigs>

describe('pipelinePluginConfigurationLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['resolves to null on a 404 so the scene renders its not-found state', 404, 'loadPluginConfigSuccess'],
        ['still fails on other errors', 500, 'loadPluginConfigFailure'],
    ])('%s', async (_name, status, expectedAction) => {
        mockApi.get.mockRejectedValue(new ApiError('Nope', status))
        const logic = pipelinePluginConfigurationLogic.build({ pluginId: null, pluginConfigId: status })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadPluginConfig', expectedAction])
        expect(logic.values.plugin).toBeNull()
    })
})

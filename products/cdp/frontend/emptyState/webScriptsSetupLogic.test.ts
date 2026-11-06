import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { hogFunctionsList } from 'products/cdp/frontend/generated/api'

import { webScriptsSetupLogic } from './webScriptsSetupLogic'

jest.mock('products/cdp/frontend/generated/api', () => ({
    hogFunctionsList: jest.fn(),
}))

const mockHogFunctionsList = hogFunctionsList as jest.MockedFunction<typeof hogFunctionsList>
const mockLegacySiteAppsList = jest.spyOn(api.pipelineFrontendAppsConfigs, 'list')

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('webScriptsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    // The scene lists hog functions and legacy plugin site apps together, so the count is
    // the sum of both sources.
    it.each([
        [0, 0, 'needs-setup'],
        [1, 0, 'has-data'],
        [42, 0, 'has-data'],
        [0, 2, 'has-data'],
    ])('pushes %i hog functions and %i legacy site apps as status %s', async (hogFunctions, legacy, expected) => {
        mockHogFunctionsList.mockResolvedValue({ count: hogFunctions, next: null, previous: null, results: [] })
        mockLegacySiteAppsList.mockResolvedValue({ count: legacy, results: [] })
        const logic = webScriptsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SITE_APPS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockHogFunctionsList.mockRejectedValue(new Error('network down'))
        mockLegacySiteAppsList.mockResolvedValue({ count: 0, results: [] })
        const logic = webScriptsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SITE_APPS }).values.status).toBe('unknown')
    })
})

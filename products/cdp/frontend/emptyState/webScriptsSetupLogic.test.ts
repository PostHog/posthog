import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { hogFunctionsList } from 'products/cdp/frontend/generated/api'

import { webScriptsSetupLogic } from './webScriptsSetupLogic'

jest.mock('products/cdp/frontend/generated/api', () => ({
    hogFunctionsList: jest.fn(),
}))

const mockHogFunctionsList = hogFunctionsList as jest.MockedFunction<typeof hogFunctionsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('webScriptsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes a site_app count of %i as status %s', async (count, expected) => {
        mockHogFunctionsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = webScriptsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SITE_APPS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockHogFunctionsList.mockRejectedValue(new Error('network down'))
        const logic = webScriptsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SITE_APPS }).values.status).toBe('unknown')
    })
})

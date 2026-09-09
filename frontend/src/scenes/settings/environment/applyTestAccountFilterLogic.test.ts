import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { insightsBulkSetTestAccountFilterCreate } from 'products/product_analytics/frontend/generated/api'

import { applyTestAccountFilterLogic } from './applyTestAccountFilterLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), info: jest.fn(), error: jest.fn() },
}))
jest.mock('products/product_analytics/frontend/generated/api', () => ({
    insightsBulkSetTestAccountFilterCreate: jest.fn(),
}))

const mockedApi = insightsBulkSetTestAccountFilterCreate as jest.Mock
const mockedToast = lemonToast as jest.Mocked<typeof lemonToast>

describe('applyTestAccountFilterLogic', () => {
    let logic: ReturnType<typeof applyTestAccountFilterLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = applyTestAccountFilterLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    // A project of only legacy insights leaves every other count at zero, so without `legacy` in the
    // summary the run reports that nothing needed changing while those insights still filter the other way.
    it('names insights held back for their storage format rather than reporting nothing to do', async () => {
        mockedApi.mockResolvedValue({ updated: 0, unchanged: 0, unsupported: 0, skipped: 0, legacy: 3 })

        logic.actions.applyToExistingInsights(true)
        await expectLogic(logic).toFinishAllListeners()

        expect(mockedToast.success).not.toHaveBeenCalled()
        const [message] = mockedToast.info.mock.calls[0]
        expect(message).toContain('No insights changed.')
        expect(message).toContain('3 saved in an older format')
    })
})

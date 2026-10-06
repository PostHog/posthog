import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'

import { insightsBulkSetDefaultFiltersCreate } from 'products/product_analytics/frontend/generated/api'

import { applyDefaultFiltersLogic } from './applyDefaultFiltersLogic'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { success: jest.fn(), info: jest.fn(), error: jest.fn() },
}))
jest.mock('products/product_analytics/frontend/generated/api', () => ({
    insightsBulkSetDefaultFiltersCreate: jest.fn(),
}))

const mockedApi = insightsBulkSetDefaultFiltersCreate as jest.Mock
const mockedToast = lemonToast as jest.Mocked<typeof lemonToast>

describe('applyDefaultFiltersLogic', () => {
    let logic: ReturnType<typeof applyDefaultFiltersLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = applyDefaultFiltersLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([true, false])(
        'sends enabled=%s to the default filters endpoint and reports the result',
        async (enabled) => {
            mockedApi.mockResolvedValue({ updated: 2, unchanged: 0, unsupported: 1, skipped: 0, legacy: 0 })

            logic.actions.applyToExistingInsights(enabled)
            await expectLogic(logic).toFinishAllListeners()

            expect(mockedApi).toHaveBeenCalledWith(expect.any(String), { enabled })
            const [message] = mockedToast.success.mock.calls[0]
            expect(message).toContain(`Turned default filters ${enabled ? 'on' : 'off'} for 2 insights.`)
            expect(message).toContain('1 with no setting for default filters, like SQL insights')
        }
    )
})

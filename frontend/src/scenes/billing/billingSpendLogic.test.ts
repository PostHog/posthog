import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { BILLING_USAGE_QUERY_TOO_LARGE_CODE } from './billingBreakdownError'
import { billingSpendLogic } from './billingSpendLogic'

describe('billingSpendLogic loader', () => {
    let logic: ReturnType<typeof billingSpendLogic.build>
    let toastErrorSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
    })

    afterEach(() => {
        logic?.unmount()
        toastErrorSpy.mockRestore()
    })

    it('handles query-size errors without failing the loader', async () => {
        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
                '/api/billing/spend/': () => [
                    400,
                    { code: BILLING_USAGE_QUERY_TOO_LARGE_CODE, detail: 'Select a product.' },
                ],
            },
        })

        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

        logic = billingSpendLogic()
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadBillingSpendSuccess'])
            .toNotHaveDispatchedActions(['loadBillingSpendFailure'])
            .toFinishAllListeners()

        expect(logic.values.billingSpendError).toEqual({
            code: BILLING_USAGE_QUERY_TOO_LARGE_CODE,
            detail: 'Select a product.',
        })
        expect(toastErrorSpy).not.toHaveBeenCalled()
    })

    it('does not let a superseded too-large error overwrite newer spend data', async () => {
        const validSpendResponse = {
            status: 'ok',
            type: 'timeseries',
            customer_id: 'cus_1',
            results: [
                {
                    id: 0,
                    label: 'Product analytics',
                    data: [1, 2, 3],
                    dates: ['2026-08-01', '2026-08-02', '2026-08-03'],
                    breakdown_type: 'type',
                    breakdown_value: 'product_analytics',
                },
            ],
        }

        useMocks({
            get: {
                '/api/billing': () => [200, billingJson],
            },
        })

        const realApiGet = api.get.bind(api)
        let rejectStaleSpend: (error: unknown) => void = () => {}
        const staleSpend = new Promise((_resolve, reject) => {
            rejectStaleSpend = reject
        })
        let spendCalls = 0
        jest.spyOn(api, 'get').mockImplementation((url: string, options?: any): any => {
            if (url.startsWith('api/billing/spend/')) {
                spendCalls += 1
                // The first (older, oversized) request stays in flight until we release it below.
                return spendCalls === 1 ? staleSpend : Promise.resolve(validSpendResponse)
            }
            return realApiGet(url, options)
        })

        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()

        logic = billingSpendLogic()
        logic.mount() // afterMount fires the first (stale) load, left pending

        // A second load supersedes the first and lands the narrowed, valid response.
        logic.actions.loadBillingSpend()
        await expectLogic(logic).toDispatchActions(['loadBillingSpendSuccess'])
        expect(logic.values.billingSpendResponse).toEqual(validSpendResponse)

        // The older request now fails as too-large; its breakpoint must swallow it
        // instead of writing null over the valid response and raising the banner.
        rejectStaleSpend({ code: BILLING_USAGE_QUERY_TOO_LARGE_CODE, detail: 'Select a product.' })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(logic.values.billingSpendResponse).toEqual(validSpendResponse)
        expect(logic.values.billingSpendError).toBeNull()
        expect(toastErrorSpy).not.toHaveBeenCalled()
    })
})

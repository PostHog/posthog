import { expectLogic } from 'kea-test-utils'

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
})

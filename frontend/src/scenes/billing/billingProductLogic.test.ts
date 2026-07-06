import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type } from '~/types'

const product = (overrides: Partial<BillingProductV2Type>): BillingProductV2Type =>
    ({
        type: 'product_analytics',
        subscribed: true,
        addons: [],
        plans: [],
        tiers: null,
        current_usage: 0,
        usage_limit: null,
        percentage_usage: 0,
        ...overrides,
    }) as unknown as BillingProductV2Type

describe('billingProductLogic billing limit submit', () => {
    let dialogSpy: jest.SpyInstance

    beforeEach(() => {
        initKeaTests()
        useMocks({ get: { '/api/billing': () => [200, {}] }, patch: { '/api/billing': () => [200, {}] } })
        billingLogic.mount()
        dialogSpy = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
    })

    afterEach(() => {
        dialogSpy.mockRestore()
    })

    it('alert-only products skip the enforced-limit warning dialogs entirely', async () => {
        // An alert below current/projected spend is the NORMAL way to use an alert — the
        // "data will be dropped" / "limit will be set to current usage" dialogs describe
        // enforcement that never happens for alert-only products.
        const storage = product({
            type: 'managed_data_warehouse_storage',
            alert_only: true,
            current_amount_usd: '3.74',
            projected_amount_usd: '27.00',
        })
        const logic = billingProductLogic({ product: storage })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setBillingLimitInput(2)
            logic.actions.submitBillingLimitInput()
        }).toDispatchActions(['updateBillingLimits'])

        expect(dialogSpy).not.toHaveBeenCalled()
    })

    it('enforced products still get the warning dialog when the limit is below current spend', async () => {
        const analytics = product({
            type: 'product_analytics',
            current_amount_usd: '700.00',
            projected_amount_usd: '900.00',
        })
        const logic = billingProductLogic({ product: analytics })
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.setBillingLimitInput(100)
            logic.actions.submitBillingLimitInput()
        }).toFinishAllListeners()

        expect(dialogSpy).toHaveBeenCalledTimes(1)
    })
})

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

// Imported from the source module rather than the `@posthog/lemon-ui` barrel so the spy below
// replaces `.error` on the same `lemonToast` singleton the logic calls at runtime (see the same
// note in paymentEntryLogic.test.ts).
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { defaultPlatformAddons } from '~/mocks/fixtures/_billing_platform_addons'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingPlan, BillingProductV2AddonType, BillingType } from '~/types'

// Scale is a flat-rate platform add-on ($750/mo) — the exact shape that used to charge immediately.
const scaleAddon = defaultPlatformAddons.find((addon) => addon.type === BillingPlan.Scale) as BillingProductV2AddonType

const seedBilling = async (billing: Partial<BillingType>): Promise<void> => {
    useMocks({ get: { '/api/billing': () => [200, billing] } })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

describe('billingProductLogic — confirm purchase modal', () => {
    let logic: ReturnType<typeof billingProductLogic.build>
    let toastErrorSpy: jest.SpyInstance

    beforeEach(async () => {
        initKeaTests()
        toastErrorSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => ({ id: 'x' }) as any)
        // A card-on-file paying customer is the only one who reaches the flat-rate "Add" button.
        await seedBilling({ customer_id: 'cus_test', subscription_level: 'paid' })
    })

    afterEach(() => {
        logic?.unmount()
        toastErrorSpy.mockRestore()
    })

    it('opens and closes the modal via show/hide actions', async () => {
        logic = billingProductLogic({ product: scaleAddon })
        logic.mount()

        await expectLogic(logic, () => logic.actions.showConfirmPurchaseModal()).toMatchValues({
            confirmPurchaseModalOpen: true,
        })
        await expectLogic(logic, () => logic.actions.hideConfirmPurchaseModal()).toMatchValues({
            confirmPurchaseModalOpen: false,
        })
    })

    it('confirming the purchase activates the add-on with its upgrade plan', async () => {
        // Respond with an error so activation stops before any real-charge side effects, while still
        // proving the request fired with the right add-on + plan.
        const activate = jest.fn(() => [200, { success: false, error: 'stop before charge' }] as [number, unknown])
        useMocks({ post: { '/api/billing/activate': activate } })
        logic = billingProductLogic({ product: scaleAddon })
        logic.mount()

        await expectLogic(logic, () => logic.actions.confirmProductPurchase())
            .toDispatchActions([
                'confirmProductPurchase',
                (a) =>
                    a.type === logic.actionTypes.handleProductUpgrade &&
                    a.payload.products === `${scaleAddon.type}:${scaleAddon.plans[0].plan_key}`,
            ])
            .toFinishAllListeners()

        expect(activate).toHaveBeenCalled()
    })

    it('auto-closes the modal once activation finishes', async () => {
        useMocks({
            post: { '/api/billing/activate': () => [200, { success: false, error: 'x' }] as [number, unknown] },
        })
        logic = billingProductLogic({ product: scaleAddon })
        logic.mount()
        logic.actions.showConfirmPurchaseModal()
        expect(logic.values.confirmPurchaseModalOpen).toBe(true)

        await expectLogic(logic, () => logic.actions.confirmProductPurchase())
            .toFinishAllListeners()
            .toMatchValues({ confirmPurchaseModalOpen: false })
    })

    it('does nothing when the product has no upgrade plan', async () => {
        const activate = jest.fn(() => [200, { success: true }] as [number, unknown])
        useMocks({ post: { '/api/billing/activate': activate } })
        const productWithoutPlans = { ...scaleAddon, type: BillingPlan.Boost, plans: [] } as BillingProductV2AddonType
        logic = billingProductLogic({ product: productWithoutPlans })
        logic.mount()

        await expectLogic(logic, () => logic.actions.confirmProductPurchase()).toFinishAllListeners()

        expect(activate).not.toHaveBeenCalled()
    })
})

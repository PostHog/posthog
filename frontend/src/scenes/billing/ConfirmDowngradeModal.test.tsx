/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { expectLogic } from 'kea-test-utils'

import { billingLogic, GRANDFATHERED_EVENTS_RETENTION_PLAN_KEY } from 'lib/logic/billing/billingLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import { defaultPlatformAddons } from '~/mocks/fixtures/_billing_platform_addons'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AvailableFeature, BillingPlan, BillingProductV2AddonType } from '~/types'

import { billingProductLogic } from './billingProductLogic'
import { ConfirmDowngradeModal } from './ConfirmDowngradeModal'
import { EventsRetentionDowngradeNotice } from './EventsRetentionDowngradeNotice'

const RETENTION_ENDS = /ends that permanently/

const platformAddon = (type: BillingPlan, years: number, subscribed: boolean): BillingProductV2AddonType => {
    const addon = defaultPlatformAddons.find((addon) => addon.type === type)!
    return {
        ...addon,
        subscribed,
        plans: addon.plans.map((plan) => ({
            ...plan,
            current_plan: subscribed,
            features: [
                ...plan.features,
                {
                    key: AvailableFeature.PRODUCT_ANALYTICS_DATA_RETENTION,
                    name: 'Data retention',
                    limit: years,
                    unit: 'years',
                },
            ],
        })),
    }
}

const boost = platformAddon(BillingPlan.Boost, 3, false)

const seedBilling = async (currentAddon: BillingProductV2AddonType): Promise<void> => {
    const [freePlan, paidPlan] = billingJson.products[0].plans
    // Billing lists only the free plan and the 7-year plan for these customers.
    const analyticsPlans = [
        { ...freePlan, current_plan: false },
        { ...paidPlan, plan_key: GRANDFATHERED_EVENTS_RETENTION_PLAN_KEY, current_plan: true },
    ]
    useMocks({
        get: {
            '/api/billing': () => [
                200,
                {
                    ...billingJson,
                    subscription_level: 'paid',
                    products: billingJson.products.map((product) =>
                        product.type === 'product_analytics'
                            ? { ...product, plans: analyticsPlans }
                            : product.type === 'platform_and_support'
                              ? { ...product, addons: [boost, currentAddon] }
                              : product
                    ),
                },
            ],
            '/api/organizations/:organization_id/events_retention_setting/downgrade_deletion_count/': {
                retention_months: 36,
                events_deleted: 1200,
            },
        },
    })
    billingLogic.mount()
    await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
}

describe('ConfirmDowngradeModal on the 7-year events retention plan', () => {
    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it.each([
        { current: BillingPlan.Scale, years: 5, notices: 1 },
        { current: BillingPlan.Teams, years: 3, notices: 0 },
    ])('shows $notices retention notice(s) going from $current ($years years) to Boost', async (testCase) => {
        await seedBilling(platformAddon(testCase.current, testCase.years, true))
        const logic = billingProductLogic({ product: boost })
        logic.mount()
        logic.actions.showConfirmDowngradeModal()
        render(
            <Provider>
                <ConfirmDowngradeModal product={boost} />
            </Provider>
        )

        expect(screen.getByText('Downgrade to Boost?')).toBeInTheDocument()
        expect(screen.queryAllByText(RETENTION_ENDS)).toHaveLength(testCase.notices)
    })

    it('warns that removing the platform package ends 7-year retention', async () => {
        await seedBilling(platformAddon(BillingPlan.Scale, 5, true))
        render(
            <Provider>
                <EventsRetentionDowngradeNotice
                    plansAfterChange={[billingLogic.values.productAnalyticsPlanAfterPackageDowngrade]}
                />
            </Provider>
        )

        expect(screen.getByText(RETENTION_ENDS)).toBeInTheDocument()
    })
})

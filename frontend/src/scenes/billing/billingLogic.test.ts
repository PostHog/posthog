import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { billingLogic } from 'scenes/billing/billingLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingType } from '~/types'

const creditOverviewResponse = {
    eligible: false,
    estimated_monthly_credit_amount_usd: null,
    status: 'none',
    invoice_url: null,
    collection_method: null,
    cc_last_four: null,
    email: null,
    credit_brackets: [],
}

const productWithUsage = (
    percentageUsage: number,
    overrides: Partial<BillingProductV2Type> = {}
): BillingProductV2Type => ({
    ...billingJson.products[0],
    type: ProductKey.PRODUCT_ANALYTICS,
    usage_key: 'events',
    name: 'Product analytics',
    subscribed: true,
    percentage_usage: percentageUsage,
    current_usage: Math.round(percentageUsage * 100),
    usage_limit: percentageUsage > 0 ? 100 : null,
    has_exceeded_limit: percentageUsage >= 1,
    ...overrides,
})

const billingWithProducts = (
    products: BillingProductV2Type[],
    customLimitsUsd: BillingType['custom_limits_usd'] = {}
): BillingType => ({
    ...billingJson,
    products,
    custom_limits_usd: customLimitsUsd,
})

describe('billingLogic', () => {
    let billingState: BillingType

    beforeEach(() => {
        billingState = billingWithProducts([productWithUsage(0.5)])
        useMocks({
            get: {
                '/_preflight': [200, { ...preflightJson, cloud: true }],
                '/api/billing': () => [200, billingState],
                '/api/billing/credits/overview': [200, creditOverviewResponse],
            },
        })
        initKeaTests()
    })

    it.each(['/organization/billing', '/organization/billing/overview'])(
        'restores product deep-link scrolling from %s after mount',
        (pathname) => {
            billingLogic.mount()
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })

            expect(billingLogic.values.scrollToProductKey).toBe(ProductKey.REPLAY_VISION)
        }
    )

    it.each(['/organization/billing', '/organization/billing/overview'])(
        'restores product deep-link scrolling from %s on initial mount',
        (pathname) => {
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })
            billingLogic.mount()

            expect(billingLogic.values.scrollToProductKey).toBe(ProductKey.REPLAY_VISION)
        }
    )

    it.each(['/organization/billing/usage', '/organization/billing/spend'])(
        'does not restore product deep-link scrolling from %s after mount',
        (pathname) => {
            billingLogic.mount()
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })

            expect(billingLogic.values.scrollToProductKey).toBe(null)
        }
    )

    it.each(['/organization/billing/usage', '/organization/billing/spend'])(
        'does not restore product deep-link scrolling from %s on initial mount',
        (pathname) => {
            router.actions.push(pathname, { products: ProductKey.REPLAY_VISION })
            billingLogic.mount()

            expect(billingLogic.values.scrollToProductKey).toBe(null)
        }
    )

    it('treats exactly 100% usage as a reached limit alert', async () => {
        billingState = billingWithProducts([productWithUsage(1)])
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.billingAlert).toMatchObject({
            status: 'error',
            title: 'Usage limit reached',
            message: expect.stringContaining('You have reached the usage limit for Product analytics.'),
            productKey: ProductKey.PRODUCT_ANALYTICS,
        })
    })

    it('clears a stale usage limit alert when refreshed billing data no longer qualifies', async () => {
        billingState = billingWithProducts([productWithUsage(1)])
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.billingAlert?.title).toBe('Usage limit reached')

        billingState = billingWithProducts([productWithUsage(0)])
        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.billingAlert).toBeNull()
    })

    it('unregisters removed custom limit analytics properties', async () => {
        const registerSpy = jest.spyOn(posthog, 'register')
        const unregisterSpy = jest.spyOn(posthog, 'unregister')
        jest.spyOn(posthog, 'get_property').mockImplementation((property) =>
            property === 'custom_limits_usd.product_analytics' ? 100 : undefined
        )
        billingState = billingWithProducts([productWithUsage(0.5)], { [ProductKey.PRODUCT_ANALYTICS]: 100 })
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()
        registerSpy.mockClear()
        unregisterSpy.mockClear()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(registerSpy).toHaveBeenCalledWith(
            expect.objectContaining({
                'custom_limits_usd.product_analytics': 100,
            })
        )

        billingState = billingWithProducts([])
        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(unregisterSpy).toHaveBeenCalledWith('custom_limits_usd.product_analytics')
        const lastRegisterPayload = registerSpy.mock.calls[registerSpy.mock.calls.length - 1][0]
        expect(lastRegisterPayload).not.toHaveProperty('custom_limits_usd.product_analytics')

        billingState = billingWithProducts([productWithUsage(0.5)], { [ProductKey.PRODUCT_ANALYTICS]: 100 })
        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()
        unregisterSpy.mockClear()

        billingState = billingWithProducts([productWithUsage(0.5)], { [ProductKey.PRODUCT_ANALYTICS]: null })
        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(unregisterSpy).toHaveBeenCalledWith('custom_limits_usd.product_analytics')
    })
})

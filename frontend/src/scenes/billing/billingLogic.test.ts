import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { BillingAPIErrorCodes, billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

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

const EXTERNAL_INVOICES_URL = 'https://vercel.com/example-team/~/integrations/posthog/icfg_example/invoices'
const HOSTED_INVOICE_URL = 'https://invoice.stripe.com/i/acct_example/test_example'

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

type BillingAccessCase = {
    name: string
    membershipLevel: OrganizationMembershipLevel
    flags: Record<string, string | boolean>
    expected: {
        canAccessBilling: boolean
        canViewUsageAndSpend: boolean
        canOnlyViewUsageAndSpend: boolean
        billingEntryUrl: string | null
    }
}

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
        expect(billingLogic.values.isProductAtOrOverUsageLimit(ProductKey.PRODUCT_ANALYTICS)).toBe(true)
    })

    it('does not treat usage below 100% as at the product limit', async () => {
        billingState = billingWithProducts([productWithUsage(0.99)])
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.isProductAtOrOverUsageLimit(ProductKey.PRODUCT_ANALYTICS)).toBe(false)
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

    it('preserves billing error URL alerts when refreshed billing data has no managed alert', async () => {
        billingState = billingWithProducts([productWithUsage(0)])
        router.actions.push('/organization/billing', { billing_error: 'Checkout failed' })
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()

        expect(billingLogic.values.billingAlert).toMatchObject({
            status: 'error',
            title: 'Error',
            message: 'Checkout failed',
            contactSupport: true,
        })

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.billingAlert).toMatchObject({
            status: 'error',
            title: 'Error',
            message: 'Checkout failed',
            contactSupport: true,
        })
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

    it.each<BillingAccessCase>([
        {
            name: 'member with the read grant',
            membershipLevel: OrganizationMembershipLevel.Member,
            flags: {
                [FEATURE_FLAGS.MEMBER_BILLING_USAGE_SPEND_READ_ACCESS]: true,
            },
            expected: {
                canAccessBilling: false,
                canViewUsageAndSpend: true,
                canOnlyViewUsageAndSpend: true,
                billingEntryUrl: urls.organizationBillingSection('usage'),
            },
        },
        {
            name: 'admin when owner-only billing is off',
            membershipLevel: OrganizationMembershipLevel.Admin,
            flags: {
                [FEATURE_FLAGS.OWNER_ONLY_BILLING]: false,
            },
            expected: {
                canAccessBilling: true,
                canViewUsageAndSpend: true,
                canOnlyViewUsageAndSpend: false,
                billingEntryUrl: urls.organizationBillingSection('overview'),
            },
        },
        {
            name: 'admin when owner-only billing is on',
            membershipLevel: OrganizationMembershipLevel.Admin,
            flags: {
                [FEATURE_FLAGS.OWNER_ONLY_BILLING]: true,
            },
            expected: {
                canAccessBilling: false,
                canViewUsageAndSpend: false,
                canOnlyViewUsageAndSpend: false,
                billingEntryUrl: null,
            },
        },
        {
            name: 'owner when owner-only billing is on',
            membershipLevel: OrganizationMembershipLevel.Owner,
            flags: {
                [FEATURE_FLAGS.OWNER_ONLY_BILLING]: true,
            },
            expected: {
                canAccessBilling: true,
                canViewUsageAndSpend: true,
                canOnlyViewUsageAndSpend: false,
                billingEntryUrl: urls.organizationBillingSection('overview'),
            },
        },
    ])('sets billing access selectors for $name', ({ membershipLevel, flags, expected }) => {
        featureFlagLogic.mount()
        organizationLogic.mount()
        billingLogic.mount()

        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            membership_level: membershipLevel,
        })
        featureFlagLogic.actions.setFeatureFlags(
            Object.entries(flags)
                .filter(([, value]) => value)
                .map(([key]) => key),
            flags
        )

        expect(billingLogic.values.canAccessBilling).toBe(expected.canAccessBilling)
        expect(billingLogic.values.canViewUsageAndSpend).toBe(expected.canViewUsageAndSpend)
        expect(billingLogic.values.canOnlyViewUsageAndSpend).toBe(expected.canOnlyViewUsageAndSpend)
        expect(billingLogic.values.billingEntryUrl).toBe(expected.billingEntryUrl)
    })

    it.each<{
        name: string
        externalInvoicesUrl?: string
        openInvoices: { count: number; link: string | null }
        loadBillingFirst: boolean
        expectedLink: string | undefined
    }>([
        {
            name: 'the hosted invoice when one invoice is open',
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            loadBillingFirst: true,
            expectedLink: HOSTED_INVOICE_URL,
        },
        {
            name: 'the Stripe portal when several invoices are open',
            openInvoices: { count: 2, link: null },
            loadBillingFirst: true,
            expectedLink: billingJson.stripe_portal_url,
        },
        {
            name: 'the external provider instead of the hosted invoice',
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            loadBillingFirst: true,
            expectedLink: EXTERNAL_INVOICES_URL,
        },
        {
            name: 'the external provider instead of the Stripe portal',
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            openInvoices: { count: 2, link: null },
            loadBillingFirst: true,
            expectedLink: EXTERNAL_INVOICES_URL,
        },
        {
            name: 'the external provider when invoices load before billing',
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            loadBillingFirst: false,
            expectedLink: EXTERNAL_INVOICES_URL,
        },
    ])(
        'links the open invoice banner to $name',
        async ({ externalInvoicesUrl, openInvoices, loadBillingFirst, expectedLink }) => {
            billingState = { ...billingState, external_billing_provider_invoices_url: externalInvoicesUrl }
            useMocks({ get: { '/api/billing/get_invoices': [200, openInvoices] } })
            billingLogic.mount()
            await expectLogic(preflightLogic).toFinishAllListeners()

            if (loadBillingFirst) {
                await expectLogic(billingLogic, () => {
                    billingLogic.actions.loadBilling()
                }).toFinishAllListeners()
            }
            await expectLogic(billingLogic, () => {
                billingLogic.actions.loadInvoices()
            }).toFinishAllListeners()

            expect(billingLogic.values.billingError?.action.to).toBe(expectedLink)
        }
    )

    it.each<{
        name: string
        code: BillingAPIErrorCodes
        externalInvoicesUrl?: string
        invoiceLink: string | null
        expectedLink: string | undefined
    }>([
        {
            name: 'open invoices to the Stripe portal',
            code: BillingAPIErrorCodes.OPEN_INVOICES_ERROR,
            invoiceLink: null,
            expectedLink: billingJson.stripe_portal_url,
        },
        {
            name: 'an unpaid invoice to its hosted invoice',
            code: BillingAPIErrorCodes.COULD_NOT_PAY_INVOICES_ERROR,
            invoiceLink: HOSTED_INVOICE_URL,
            expectedLink: HOSTED_INVOICE_URL,
        },
        {
            name: 'open invoices to the external provider',
            code: BillingAPIErrorCodes.OPEN_INVOICES_ERROR,
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            invoiceLink: null,
            expectedLink: EXTERNAL_INVOICES_URL,
        },
        {
            name: 'an unpaid invoice to the external provider',
            code: BillingAPIErrorCodes.COULD_NOT_PAY_INVOICES_ERROR,
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            invoiceLink: HOSTED_INVOICE_URL,
            expectedLink: EXTERNAL_INVOICES_URL,
        },
    ])('links the unsubscribe error for $name', async ({ code, externalInvoicesUrl, invoiceLink, expectedLink }) => {
        billingState = { ...billingState, external_billing_provider_invoices_url: externalInvoicesUrl }
        useMocks({
            post: {
                '/api/billing/deactivate': [400, { code, detail: 'Pay your open invoices first.', link: invoiceLink }],
            },
        })
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()
        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.deactivateProduct(ProductKey.PRODUCT_ANALYTICS)
        }).toFinishAllListeners()

        expect(billingLogic.values.unsubscribeError?.link.props.to).toBe(expectedLink)
    })
})

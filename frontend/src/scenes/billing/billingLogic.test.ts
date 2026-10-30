/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { MOCK_DEFAULT_ORGANIZATION } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { BillingAPIErrorCodes, billingLogic } from 'scenes/billing/billingLogic'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { useMocks } from '~/mocks/jest'
import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { BillingProductV2Type, BillingProvider, BillingType, StartupProgramLabel } from '~/types'

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
const UNSUBSCRIBE_ERROR_DETAIL = 'Pay your open invoices first.'
const VERCEL_NOTICE =
    'Billing for this organization is managed by Vercel, including the payment method and invoices. To cap your spend, set a billing limit on each product on this page.'
const VERCEL_DISABLED_REASON =
    'Billing for this organization is managed by Vercel. Contact support to change your plan.'

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
    let billingAnswer: [number, unknown] | null
    let creditOverviewAnswer: [number, unknown]

    beforeEach(() => {
        billingState = billingWithProducts([productWithUsage(0.5)])
        billingAnswer = null
        creditOverviewAnswer = [200, creditOverviewResponse]
        useMocks({
            get: {
                '/_preflight': [200, { ...preflightJson, cloud: true }],
                '/api/billing': () => billingAnswer ?? [200, billingState],
                '/api/billing/credits/overview': () => creditOverviewAnswer,
            },
        })
        initKeaTests()
    })

    it.each([
        { case: 'an empty body', answer: [200, null] as [number, unknown] },
        { case: 'a server error', answer: [500, { detail: 'A server error occurred.' }] as [number, unknown] },
    ])('keeps the last billing state when billing answers with $case', async ({ answer }) => {
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling())
            .toFinishAllListeners()
            .clearHistory()
        const loaded = billingLogic.values.billing
        expect(loaded).not.toBeNull()

        billingAnswer = answer
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling())
            .toDispatchActions(['loadBillingSuccess'])
            .toNotHaveDispatchedActions(['loadBillingFailure'])
            .toFinishAllListeners()

        expect(billingLogic.values.billing).toEqual(loaded)
    })

    it('keeps ambient credit and profile refreshes for an unscoped successful billing load', async () => {
        billingState = { ...billingState, has_active_subscription: true }
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling()).toFinishAllListeners()
        const organization = organizationLogic.values.currentOrganization!
        const user = userLogic.values.user!
        await new Promise((resolve) => setTimeout(resolve, 0))
        await expectLogic(billingLogic).toFinishAllListeners()
        const ambientCredits = jest.fn(() => [200, creditOverviewResponse])
        const ambientUser = jest.fn(() => [200, user])
        const ambientOrganization = jest.fn(() => [200, organization])
        useMocks({
            get: {
                '/api/billing/credits/overview': ambientCredits,
                '/api/users/@me': ambientUser,
                '/api/organizations/@current': ambientOrganization,
            },
        })
        router.actions.push('/organization/billing', { success: 'true' })

        jest.useFakeTimers()
        try {
            const expectation = expectLogic(billingLogic, () => {
                billingLogic.actions.loadBilling()
            }).toFinishAllListeners()
            await jest.advanceTimersByTimeAsync(2000)
            await expectation
            await expectLogic(userLogic).toFinishAllListeners()
            await expectLogic(organizationLogic).toFinishAllListeners()

            expect(ambientCredits).toHaveBeenCalled()
            expect(ambientUser).toHaveBeenCalled()
            expect(ambientOrganization).toHaveBeenCalled()
            expect(router.values.searchParams).toEqual({})
        } finally {
            jest.useRealTimers()
        }
    })

    it('reports a failed limit update as a failure, so the limit editor keeps the value', async () => {
        useMocks({ patch: { '/api/billing': () => [500, { detail: 'A server error occurred.' }] } })
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling())
            .toFinishAllListeners()
            .clearHistory()
        const loaded = billingLogic.values.billing

        await expectLogic(billingLogic, () => billingLogic.actions.updateBillingLimits({ product_analytics: 100 }))
            .toDispatchActions(['updateBillingLimitsFailure'])
            .toNotHaveDispatchedActions(['updateBillingLimitsSuccess'])
            .toFinishAllListeners()

        expect(billingLogic.values.billing).toEqual(loaded)
    })

    it('keeps the last credit overview when billing answers with an empty body', async () => {
        billingState = { ...billingState, has_active_subscription: true }
        creditOverviewAnswer = [200, null]
        billingLogic.mount()
        await expectLogic(billingLogic, () => billingLogic.actions.loadBilling())
            .toFinishAllListeners()
            .clearHistory()

        await expectLogic(billingLogic, () => billingLogic.actions.loadCreditOverview())
            .toDispatchActions(['loadCreditOverviewSuccess'])
            .toNotHaveDispatchedActions(['loadCreditOverviewFailure'])
            .toFinishAllListeners()

        expect(billingLogic.values.creditOverview.estimated_monthly_credit_amount_usd).toBeNull()
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

    it.each([
        {
            name: 'self-serve billing',
            billing: {},
            expectedMessage:
                'You have reached the usage limit for Product analytics. Please upgrade your plan or data loss may occur.',
        },
        {
            name: 'partner-managed billing',
            billing: { customer_id: '', billing_managed_by_partner: { partner_name: 'Example Partner' } },
            expectedMessage:
                'You have reached the usage limit for Product analytics. Data loss may occur. Billing for this organization is managed by Example Partner. Contact them to change your plan or payment details.',
        },
        {
            name: 'Vercel-managed billing without an active subscription',
            billing: { billing_provider: BillingProvider.Vercel, has_active_subscription: false },
            expectedMessage: `You have reached the usage limit for Product analytics. Data loss may occur. ${VERCEL_DISABLED_REASON}`,
        },
    ])('treats exactly 100% usage as a reached limit alert with $name', async ({ billing, expectedMessage }) => {
        billingState = { ...billingWithProducts([productWithUsage(1, { subscribed: false })]), ...billing }
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.billingAlert).toMatchObject({
            status: 'error',
            title: 'Usage limit reached',
            message: expectedMessage,
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

    it.each([
        {
            name: 'YC credits left that renew',
            label: StartupProgramLabel.YC,
            credits: '100.00',
            renew: true,
            expected: 'renewing',
        },
        {
            name: 'YC credits used that renew',
            label: StartupProgramLabel.YC,
            credits: undefined,
            renew: true,
            expected: 'used_until_renewal',
        },
        {
            name: 'YC credits left that do not renew',
            label: StartupProgramLabel.YC,
            credits: '100.00',
            renew: false,
            expected: 'ending',
        },
        {
            name: 'YC credits used that do not renew',
            label: StartupProgramLabel.YC,
            credits: undefined,
            renew: false,
            expected: 'ended',
        },
        {
            name: 'a YC response without the renewal field',
            label: StartupProgramLabel.YC,
            credits: undefined,
            renew: undefined,
            expected: 'used_until_renewal',
        },
        {
            name: 'Startup credits used',
            label: StartupProgramLabel.Startup,
            credits: undefined,
            renew: false,
            expected: null,
        },
    ])('derives the YC credits state for $name', async ({ label, credits, renew, expected }) => {
        billingState = {
            ...billingWithProducts([productWithUsage(0.5)]),
            startup_program_label: label,
            discount_amount_usd: credits,
            startup_program_credits_renew: renew,
        }
        billingLogic.mount()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.ycCreditsState).toBe(expected)
    })

    it.each([
        { name: 'keeps the date for YC credits', label: StartupProgramLabel.YC, expected: '2024-03-15T12:00:00Z' },
        {
            name: 'moves the date to the period end for other credits',
            label: StartupProgramLabel.Startup,
            expected: '2024-03-31T00:00:00Z',
        },
    ])('$name that expire mid-period', async ({ label, expected }) => {
        billingState = {
            ...billingWithProducts([productWithUsage(0.5)]),
            startup_program_label: label,
            amount_off_expires_at: dayjs('2024-03-15T12:00:00Z'),
            billing_period: {
                current_period_start: dayjs('2024-03-01T00:00:00Z'),
                current_period_end: dayjs('2024-03-31T00:00:00Z'),
                interval: 'month',
            },
        }
        billingLogic.mount()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.billing?.amount_off_expires_at?.toISOString()).toBe(new Date(expected).toISOString())
    })

    it.each([
        { name: 'eligible for credits', eligible: true, partnerName: 'Example Partner', shownName: 'Example Partner' },
        {
            name: 'not eligible for credits',
            eligible: false,
            partnerName: 'Example Partner',
            shownName: 'Example Partner',
        },
        { name: 'blank partner name', eligible: false, partnerName: '', shownName: 'your partner' },
    ])(
        'hides the upgrade and credits heroes when a partner manages billing ($name)',
        async ({ eligible, partnerName, shownName }) => {
            billingState = {
                ...billingJson,
                customer_id: '',
                billing_managed_by_partner: { partner_name: partnerName },
            }
            useMocks({ get: { '/api/billing/credits/overview': [200, { ...creditOverviewResponse, eligible }] } })
            billingLogic.mount()

            await expectLogic(billingLogic, () => {
                billingLogic.actions.loadBilling()
            }).toFinishAllListeners()

            expect(billingLogic.values).toMatchObject({
                showCreditCTAHero: false,
                showBillingHero: false,
                billingManagedByPartnerNotice: `Billing for this organization is managed by ${shownName}. Contact them to change your plan or payment details.`,
            })
        }
    )

    it.each<{
        name: string
        answer: [number, Partial<BillingType> | null]
        expected: {
            isBillingManagedByVercel: boolean
            billingManagedByVercelNotice: string | null
            billingManagedByVercelDisabledReason: string | null
            showBillingHero: boolean
        }
    }>([
        {
            name: 'Vercel with an active subscription',
            answer: [200, { ...billingJson, billing_provider: BillingProvider.Vercel, has_active_subscription: true }],
            expected: {
                isBillingManagedByVercel: true,
                billingManagedByVercelNotice: VERCEL_NOTICE,
                billingManagedByVercelDisabledReason: null,
                showBillingHero: true,
            },
        },
        {
            name: 'Vercel with no active subscription',
            answer: [200, { ...billingJson, billing_provider: BillingProvider.Vercel, has_active_subscription: false }],
            expected: {
                isBillingManagedByVercel: true,
                billingManagedByVercelNotice: VERCEL_DISABLED_REASON,
                billingManagedByVercelDisabledReason: VERCEL_DISABLED_REASON,
                showBillingHero: false,
            },
        },
        {
            name: 'PostHog with no active subscription',
            answer: [
                200,
                { ...billingJson, billing_provider: BillingProvider.PostHog, has_active_subscription: false },
            ],
            expected: {
                isBillingManagedByVercel: false,
                billingManagedByVercelNotice: null,
                billingManagedByVercelDisabledReason: null,
                showBillingHero: true,
            },
        },
        {
            name: 'no billing loaded',
            answer: [200, null],
            expected: {
                isBillingManagedByVercel: false,
                billingManagedByVercelNotice: null,
                billingManagedByVercelDisabledReason: null,
                showBillingHero: false,
            },
        },
    ])('sets the Vercel billing selectors for $name', async ({ answer, expected }) => {
        billingAnswer = answer
        billingLogic.mount()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values).toMatchObject(expected)
    })

    // A companion has no billing limit, so its usage percentage must not raise a limit banner.
    it.each([
        ['reached', 1.5],
        ['approaching', 0.9],
    ])('raises no %s usage limit banner for a companion', async (_name, percentageUsage) => {
        billingState = billingWithProducts([
            productWithUsage(0),
            productWithUsage(percentageUsage, {
                type: 'logs_retention_custom',
                usage_key: 'logs_retention_custom_gb_months',
                name: 'Logs custom retention',
                companion_of: 'logs',
                inclusion_only: true,
                no_billing_limit: true,
            }),
        ])
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()

        await expectLogic(billingLogic, () => {
            billingLogic.actions.loadBilling()
        }).toFinishAllListeners()

        expect(billingLogic.values.billingAlert).toBeNull()
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

    const loadOpenInvoiceBanner = async (
        billing: Partial<BillingType>,
        openInvoices: { count: number; link: string | null },
        billingLoadsFirst: boolean
    ): Promise<number> => {
        // Reading a lazy value starts its load on a timer that can outlive the test that read it.
        // Let timers from earlier tests fire before this logic mounts, so they cannot add to the count.
        await new Promise((resolve) => setTimeout(resolve, 0))
        billingState = { ...billingState, ...billing }
        let billingRequests = 0
        let releaseBilling = (): void => {}
        const billingReleased = new Promise<void>((resolve) => {
            releaseBilling = resolve
        })
        useMocks({
            get: {
                '/api/billing': async () => {
                    billingRequests += 1
                    // Only the first request waits, so a duplicate request answers and shows up in the count.
                    if (billingRequests === 1) {
                        await billingReleased
                    }
                    return [200, billingState]
                },
                '/api/billing/get_invoices': [200, openInvoices],
            },
        })
        billingLogic.mount()
        await expectLogic(preflightLogic).toFinishAllListeners()

        if (billingLoadsFirst) {
            releaseBilling()
            await expectLogic(billingLogic, () => {
                expect(billingLogic.values.billing).toBeNull()
            }).toDispatchActions(['loadBillingSuccess'])
            await expectLogic(billingLogic, () => {
                expect(billingLogic.values.billingError).toBeNull()
            }).toDispatchActions(['loadInvoicesSuccess'])
        } else {
            await expectLogic(billingLogic, () => {
                expect(billingLogic.values.billing).toBeNull()
                expect(billingLogic.values.billingError).toBeNull()
            }).toDispatchActions(['loadInvoicesSuccess'])
            releaseBilling()
        }
        await expectLogic(billingLogic).toFinishAllListeners()

        return billingRequests
    }

    const failDeactivation = async (
        billing: Partial<BillingType>,
        code: BillingAPIErrorCodes,
        invoiceLink: string | null
    ): Promise<void> => {
        billingState = { ...billingState, ...billing }
        useMocks({
            post: {
                '/api/billing/deactivate': [400, { code, detail: UNSUBSCRIBE_ERROR_DETAIL, link: invoiceLink }],
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
    }

    it.each<{
        name: string
        billingProvider?: BillingProvider
        externalInvoicesUrl?: string
        openInvoices: { count: number; link: string | null }
        billingLoadsFirst: boolean
        expectedLink: string | undefined
        expectedLabel: string
    }>([
        {
            name: 'the hosted invoice when one invoice is open',
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            billingLoadsFirst: true,
            expectedLink: HOSTED_INVOICE_URL,
            expectedLabel: 'View invoice',
        },
        {
            name: 'the Stripe portal when several invoices are open',
            openInvoices: { count: 2, link: null },
            billingLoadsFirst: true,
            expectedLink: billingJson.stripe_portal_url,
            expectedLabel: 'View invoices',
        },
        {
            name: 'the external provider instead of the hosted invoice',
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            billingLoadsFirst: true,
            expectedLink: EXTERNAL_INVOICES_URL,
            expectedLabel: 'View invoices',
        },
        {
            name: 'the external provider instead of the Stripe portal',
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            openInvoices: { count: 2, link: null },
            billingLoadsFirst: true,
            expectedLink: EXTERNAL_INVOICES_URL,
            expectedLabel: 'View invoices',
        },
        {
            name: 'the external provider when invoices finish while billing is still loading',
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            billingLoadsFirst: false,
            expectedLink: EXTERNAL_INVOICES_URL,
            expectedLabel: 'View invoices',
        },
        {
            name: 'the hosted invoice when PostHog bills the organization',
            billingProvider: BillingProvider.PostHog,
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            billingLoadsFirst: true,
            expectedLink: HOSTED_INVOICE_URL,
            expectedLabel: 'View invoice',
        },
    ])(
        'links the open invoice banner to $name',
        async ({
            billingProvider,
            externalInvoicesUrl,
            openInvoices,
            billingLoadsFirst,
            expectedLink,
            expectedLabel,
        }) => {
            const billingRequests = await loadOpenInvoiceBanner(
                { billing_provider: billingProvider, external_billing_provider_invoices_url: externalInvoicesUrl },
                openInvoices,
                billingLoadsFirst
            )

            expect(billingRequests).toBe(1)
            expect(billingLogic.values.billingError).toEqual({
                status: 'warning',
                message: expect.stringContaining(`You have ${openInvoices.count} open invoice`),
                action: { to: expectedLink, children: expectedLabel, targetBlank: true },
            })
        }
    )

    it.each([
        { name: 'one open invoice', openInvoices: { count: 1, link: HOSTED_INVOICE_URL }, billingLoadsFirst: true },
        { name: 'several open invoices', openInvoices: { count: 2, link: null }, billingLoadsFirst: true },
        {
            name: 'invoices that finish while billing is still loading',
            openInvoices: { count: 1, link: HOSTED_INVOICE_URL },
            billingLoadsFirst: false,
        },
    ])(
        'hides the open invoice banner when an external provider has no invoices page ($name)',
        async ({ openInvoices, billingLoadsFirst }) => {
            await loadOpenInvoiceBanner({ billing_provider: BillingProvider.Vercel }, openInvoices, billingLoadsFirst)

            expect(billingLogic.values.billingError).toBeNull()
        }
    )

    it.each<{
        name: string
        code: BillingAPIErrorCodes
        externalInvoicesUrl?: string
        invoiceLink: string | null
        expectedLink: string | undefined
        expectedLabel: string
    }>([
        {
            name: 'open invoices to the Stripe portal',
            code: BillingAPIErrorCodes.OPEN_INVOICES_ERROR,
            invoiceLink: null,
            expectedLink: billingJson.stripe_portal_url,
            expectedLabel: 'View invoices',
        },
        {
            name: 'an unpaid invoice to its hosted invoice',
            code: BillingAPIErrorCodes.COULD_NOT_PAY_INVOICES_ERROR,
            invoiceLink: HOSTED_INVOICE_URL,
            expectedLink: HOSTED_INVOICE_URL,
            expectedLabel: 'View invoice',
        },
        {
            name: 'open invoices to the external provider',
            code: BillingAPIErrorCodes.OPEN_INVOICES_ERROR,
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            invoiceLink: null,
            expectedLink: EXTERNAL_INVOICES_URL,
            expectedLabel: 'View invoices',
        },
        {
            name: 'an unpaid invoice to the external provider',
            code: BillingAPIErrorCodes.COULD_NOT_PAY_INVOICES_ERROR,
            externalInvoicesUrl: EXTERNAL_INVOICES_URL,
            invoiceLink: HOSTED_INVOICE_URL,
            expectedLink: EXTERNAL_INVOICES_URL,
            expectedLabel: 'View invoices',
        },
    ])(
        'links the unsubscribe error for $name',
        async ({ code, externalInvoicesUrl, invoiceLink, expectedLink, expectedLabel }) => {
            await failDeactivation({ external_billing_provider_invoices_url: externalInvoicesUrl }, code, invoiceLink)

            expect(billingLogic.values.unsubscribeError?.link.props).toMatchObject({
                to: expectedLink,
                children: expectedLabel,
            })
        }
    )

    it.each([
        { name: 'open invoices', code: BillingAPIErrorCodes.OPEN_INVOICES_ERROR, invoiceLink: null },
        {
            name: 'an unpaid invoice',
            code: BillingAPIErrorCodes.COULD_NOT_PAY_INVOICES_ERROR,
            invoiceLink: HOSTED_INVOICE_URL,
        },
    ])(
        'keeps the unsubscribe error for $name without a link when an external provider has no invoices page',
        async ({ code, invoiceLink }) => {
            await failDeactivation({ billing_provider: BillingProvider.Vercel }, code, invoiceLink)

            expect(billingLogic.values.unsubscribeError).toEqual({ detail: UNSUBSCRIBE_ERROR_DETAIL })
        }
    )
})

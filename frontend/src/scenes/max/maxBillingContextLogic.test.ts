import { expectLogic } from 'kea-test-utils'

import { dayjs } from 'lib/dayjs'
import * as billingUtils from 'scenes/billing/billing-utils'
import { BillingSpendResponse, BillingSpendResponseBreakdownType } from 'scenes/billing/billingSpendLogic'
import { BillingUsageResponse, BillingUsageResponseBreakdownType } from 'scenes/billing/billingUsageLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { BillingPlan, BillingType, HogFunctionType, StartupProgramLabel, TeamType } from '~/types'

import { billingToMaxContext, maxBillingContextLogic } from './maxBillingContextLogic'

const mockBilling: BillingType = {
    customer_id: '123',
    subscription_level: 'paid',
    has_active_subscription: true,
    billing_plan: BillingPlan.Paid,
    deactivated: false,
    current_total_amount_usd: '100.00',
    projected_total_amount_usd: '150.00',
    projected_total_amount_usd_after_discount: '135.00',
    projected_total_amount_usd_with_limit: '140.00',
    projected_total_amount_usd_with_limit_after_discount: '126.00',
    startup_program_label: StartupProgramLabel.YC,
    startup_program_label_previous: undefined,
    trial: {
        status: 'active',
        expires_at: '2024-12-31T00:00:00Z',
        target: 'paid',
        type: 'standard',
    },
    billing_period: {
        current_period_start: dayjs('2024-01-01'),
        current_period_end: dayjs('2024-01-31'),
        interval: 'month',
    },
    custom_limits_usd: {
        product_analytics: 50,
        session_replay: 30,
    },
    next_period_custom_limits_usd: {
        product_analytics: 60,
        session_replay: 40,
    },
    products: [
        {
            type: 'product_analytics',
            name: 'Product Analytics',
            description: 'Analyze user behavior',
            usage_key: 'events',
            current_usage: 1000000,
            free_allocation: 1000000,
            percentage_usage: 1.0,
            tiers: null,
            tiered: false,
            projected_amount_usd: '50.00',
            projected_amount_usd_with_limit: '45.00',
            docs_url: 'https://posthog.com/docs/product-analytics',
            headline: 'Product Analytics',
            screenshot_url: 'https://posthog.com/docs/product-analytics',
            subscribed: false,
            current_amount_usd_before_addons: '0',
            current_amount_usd: '0',
            usage_limit: 1000000,
            has_exceeded_limit: false,
            unit: 'events',
            unit_amount_usd: '0.001',
            plans: [],
            features: [],
            contact_support: false,
            inclusion_only: false,
            addons: [
                {
                    type: 'addon_1',
                    name: 'Addon 1',
                    description: 'Test addon',
                    usage_key: 'addon_events',
                    current_usage: 500,
                    usage_limit: 1000,
                    percentage_usage: 0.5,
                    projected_amount_usd: '10.00',
                    docs_url: 'https://posthog.com/docs/addon',
                    price_description: '1000',
                    image_url: 'https://posthog.com/docs/addon',
                    tiers: [],
                    tiered: false,
                    subscribed: false,
                    inclusion_only: false,
                    contact_support: false,
                    unit: 'addon_events',
                    unit_amount_usd: '0',
                    current_amount_usd: '0',
                    projected_usage: 0,
                    plans: [],
                    features: [],
                },
            ],
        },
        {
            type: 'session_replay',
            name: 'Session Replay',
            description: 'Record user sessions',
            usage_key: 'recordings',
            current_usage: 5000,
            free_allocation: 5000,
            percentage_usage: 1.0,
            tiers: [
                {
                    up_to: 15000,
                    unit_amount_usd: '0.005',
                    flat_amount_usd: '0',
                    current_amount_usd: '0',
                    current_usage: 5000,
                    projected_usage: 5000,
                    projected_amount_usd: '30.00',
                },
            ],
            tiered: true,
            projected_amount_usd: '30.00',
            projected_amount_usd_with_limit: '25.00',
            docs_url: 'https://posthog.com/docs/session-replay',
            addons: [],
            headline: 'Session Replay',
            screenshot_url: 'https://posthog.com/docs/session-replay',
            subscribed: false,
            current_amount_usd_before_addons: '0',
            current_amount_usd: '0',
            usage_limit: 15000,
            has_exceeded_limit: false,
            unit: 'recordings',
            unit_amount_usd: '0.005',
            plans: [],
            features: [],
            contact_support: false,
            inclusion_only: false,
        },
        {
            type: 'platform_and_support',
            name: 'Platform & Support',
            description: 'Platform features and support',
            usage_key: 'events',
            headline: 'Platform & Support',
            screenshot_url: 'https://posthog.com/docs/platform-and-support',
            docs_url: 'https://posthog.com/docs/platform-and-support',
            current_amount_usd_before_addons: '0',
            current_amount_usd: '0',
            usage_limit: 1000000,
            subscribed: false,
            tiered: false,
            percentage_usage: 0,
            has_exceeded_limit: false,
            unit: 'events',
            unit_amount_usd: '0',
            features: [],
            contact_support: false,
            inclusion_only: false,
            addons: [],
            plans: [
                {
                    name: 'Startup',
                    description: 'For early stage companies',
                    current_plan: false,
                    features: [],
                    image_url: 'https://posthog.com/docs/platform-and-support',
                    docs_url: 'https://posthog.com/docs/platform-and-support',
                    note: 'For early stage companies',
                    unit: 'events',
                    flat_rate: false,
                    product_key: 'platform_and_support',
                    unit_amount_usd: '0',
                    contact_support: false,
                },
                {
                    name: 'Growth',
                    description: 'For growing companies',
                    current_plan: true,
                    features: [],
                    image_url: 'https://posthog.com/docs/platform-and-support',
                    docs_url: 'https://posthog.com/docs/platform-and-support',
                    note: 'For growing companies',
                    unit: 'events',
                    flat_rate: false,
                    product_key: 'platform_and_support',
                    unit_amount_usd: '0',
                    contact_support: false,
                },
                {
                    name: 'Enterprise',
                    description: 'For large organizations',
                    current_plan: false,
                    features: [],
                    image_url: 'https://posthog.com/docs/platform-and-support',
                    docs_url: 'https://posthog.com/docs/platform-and-support',
                    note: 'For large organizations',
                    unit: 'events',
                    flat_rate: false,
                    product_key: 'platform_and_support',
                    unit_amount_usd: '0',
                    contact_support: false,
                },
            ],
        },
    ],
}

const mockTeam: TeamType = {
    id: 1,
    name: 'Test Team',
    autocapture_opt_out: false,
} as TeamType

const mockBillingUsageResponse: BillingUsageResponse = {
    results: [
        {
            id: 1,
            label: '2024-01-01',
            data: [100000],
            dates: ['2024-01-01'],
            breakdown_type: BillingUsageResponseBreakdownType.TYPE,
            breakdown_value: 'events',
        },
    ],
    status: 'ok',
    type: 'timeseries',
    customer_id: '123',
}

const mockBillingSpendResponse: BillingSpendResponse = {
    results: [
        {
            id: 1,
            label: '2024-01-01',
            data: [100.0],
            dates: ['2024-01-01'],
            breakdown_type: BillingSpendResponseBreakdownType.TYPE,
            breakdown_value: 'events',
        },
    ],
    status: 'ok',
    type: 'timeseries',
    customer_id: '123',
}

const mockDestinations: HogFunctionType[] = [
    { id: '1', name: 'Destination 1', enabled: true } as HogFunctionType,
    { id: '2', name: 'Destination 2', enabled: true } as HogFunctionType,
]

describe('maxBillingContextLogic', () => {
    let logic: ReturnType<typeof maxBillingContextLogic.build>

    beforeEach(() => {
        useMocks({
            get: {
                '/api/billing/': mockBilling,
                '/api/billing/usage/': mockBillingUsageResponse,
                '/api/billing/spend/': mockBillingSpendResponse,
                '/api/billing/usage_limit_alerts/': [],
                '/api/billing/compute_spend': {},
                '/api/organizations/@current/': {
                    id: '123',
                    name: 'Test Org',
                    membership_level: 15, // OrganizationMembershipLevel.Admin
                },
                '/api/environments/@current/team/': mockTeam,
                '/api/posthog/': { feature_flags: {} },
                '/api/organizations/@current/pipeline_destinations/': { results: mockDestinations },
                '/api/environments/:team_id/pipeline-destinations': { results: mockDestinations },
                '/api/environments/:team_id/plugin_configs': { results: [] },
                '/api/organizations/@current/plugins': { results: [] },
                '/api/organizations/@current/batch_exports': { results: [] },
                '/api/projects/:project_id/pipeline_destination_configs/': { results: [] },
                '/api/environments/:team_id/batch_exports/': { results: [] },
            },
            post: {
                '/api/billing/usage': mockBillingUsageResponse,
                '/api/billing/spend': mockBillingSpendResponse,
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('billingToMaxContext', () => {
        it('returns null when billing is null', () => {
            const result = billingToMaxContext(null, {}, mockTeam, [], null, null)
            expect(result).toBeNull()
        })

        it('converts billing data to MaxBillingContext format', () => {
            const result = billingToMaxContext(
                mockBilling,
                {},
                mockTeam,
                mockDestinations,
                mockBillingUsageResponse,
                mockBillingSpendResponse
            )

            expect(result).toMatchObject({
                has_active_subscription: true,
                subscription_level: 'paid',
                billing_plan: 'paid',
                is_deactivated: false,
                total_current_amount_usd: '100.00',
                projected_total_amount_usd: '150.00',
                projected_total_amount_usd_after_discount: '135.00',
                projected_total_amount_usd_with_limit: '140.00',
                projected_total_amount_usd_with_limit_after_discount: '126.00',
                startup_program_label: 'YC',
                startup_program_label_previous: undefined,
                trial: {
                    is_active: true,
                    expires_at: '2024-12-31T00:00:00Z',
                    target: 'paid',
                },
                billing_period: {
                    current_period_start: '2024-01-01',
                    current_period_end: '2024-01-31',
                    interval: 'month',
                },
                usage_history: mockBillingUsageResponse.results,
                spend_history: mockBillingSpendResponse.results,
                settings: {
                    autocapture_on: true,
                    active_destinations: 2,
                },
            })
        })

        it('processes products correctly', () => {
            const result = billingToMaxContext(mockBilling, {}, mockTeam, [], null, null)

            expect(result?.products).toHaveLength(3)
            expect(result?.products[0]).toMatchObject({
                type: 'product_analytics',
                name: 'Product Analytics',
                description: 'Analyze user behavior',
                is_used: true,
                has_exceeded_limit: false, // percentage_usage = 1.0 means at limit, not exceeded
                current_usage: 1000000,
                usage_limit: 1000000,
                percentage_usage: 1.0,
                custom_limit_usd: 50,
                next_period_custom_limit_usd: 60,
                projected_amount_usd: '50.00',
                projected_amount_usd_with_limit: '45.00',
                docs_url: 'https://posthog.com/docs/product-analytics',
                addons: [
                    {
                        type: 'addon_1',
                        name: 'Addon 1',
                        description: 'Test addon',
                        is_used: true,
                        has_exceeded_limit: false,
                        current_usage: 500,
                        usage_limit: 1000,
                        percentage_usage: 0.5,
                        docs_url: 'https://posthog.com/docs/addon',
                        projected_amount_usd: '10.00',
                    },
                ],
            })

            expect(result?.products[1]).toMatchObject({
                type: 'session_replay',
                name: 'Session Replay',
                description: 'Record user sessions',
                is_used: true,
                has_exceeded_limit: false, // percentage_usage = 1.0 means at limit, not exceeded
                current_usage: 5000,
                usage_limit: 15000, // From first tier
                percentage_usage: 1.0,
                custom_limit_usd: 30,
                next_period_custom_limit_usd: 40,
            })
        })

        it('processes platform products with correct plan', () => {
            const result = billingToMaxContext(mockBilling, {}, mockTeam, [], null, null)

            const platformProduct = result?.products.find((p) => p.type === 'platform_and_support')
            expect(platformProduct).toMatchObject({
                type: 'platform_and_support',
                name: 'Platform & Support (Growth)',
                description: 'For growing companies',
            })
        })

        it('handles missing trial data', () => {
            const billingWithoutTrial = { ...mockBilling, trial: undefined }
            const result = billingToMaxContext(billingWithoutTrial, {}, mockTeam, [], null, null)

            expect(result?.trial).toBeUndefined()
        })

        it('handles free subscription correctly', () => {
            const freeBilling = {
                ...mockBilling,
                has_active_subscription: false,
                subscription_level: 'free' as const,
            }
            const result = billingToMaxContext(freeBilling, {}, mockTeam, [], null, null)

            expect(result?.has_active_subscription).toBe(false)
            expect(result?.subscription_level).toBe('free')
        })

        it('handles team with autocapture disabled', () => {
            const teamWithoutAutocapture = { ...mockTeam, autocapture_opt_out: true }
            const result = billingToMaxContext(mockBilling, {}, teamWithoutAutocapture, [], null, null)

            expect(result?.settings.autocapture_on).toBe(false)
        })

        it('filters addons based on feature flags when isAddonVisible is considered', () => {
            const isAddonVisibleSpy = jest.spyOn(billingUtils, 'isAddonVisible')

            // Test case 1: All addons visible
            isAddonVisibleSpy.mockReturnValue(true)
            const resultAllVisible = billingToMaxContext(mockBilling, {}, mockTeam, [], null, null)
            expect(resultAllVisible?.products[0].addons).toHaveLength(1)
            expect(resultAllVisible?.products[0].addons[0].type).toBe('addon_1')

            // Test case 2: No addons visible due to feature flags
            isAddonVisibleSpy.mockReturnValue(false)
            const resultNoneVisible = billingToMaxContext(
                mockBilling,
                { billing_hide_addon_addon_1: true },
                mockTeam,
                [],
                null,
                null
            )
            expect(resultNoneVisible?.products[0].addons).toHaveLength(0)

            // Test case 3: Verify isAddonVisible is called with correct parameters
            isAddonVisibleSpy.mockReturnValue(true)
            const featureFlags = { some_feature: true }
            billingToMaxContext(mockBilling, featureFlags, mockTeam, [], null, null)

            expect(isAddonVisibleSpy).toHaveBeenCalledWith(
                mockBilling.products[0], // The product containing the addon
                mockBilling.products[0].addons![0], // The addon itself
                featureFlags // The feature flags passed in
            )

            isAddonVisibleSpy.mockRestore()
        })
    })

    describe('maxBillingContextLogic', () => {
        beforeEach(async () => {
            logic = maxBillingContextLogic()
            logic.mount()
            // Wait for initial mount actions to complete
            await expectLogic(logic).toFinishAllListeners()
        })

        it('returns null when user is not admin or owner', async () => {
            // Remount with a mock that indicates user is not admin
            logic.unmount()
            useMocks({
                get: {
                    '/api/organizations/@current/': {
                        id: '123',
                        name: 'Test Org',
                        membership_level: 1, // OrganizationMembershipLevel.Member
                    },
                },
            })
            logic = maxBillingContextLogic()
            logic.mount()

            await expectLogic(logic).toMatchValues({
                billingContext: null,
            })
        })

        it('returns billing context when user is admin or owner', async () => {
            // Wait for all data to be loaded
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic).toMatchValues({
                billingContext: expect.objectContaining({
                    has_active_subscription: true,
                    subscription_level: 'paid',
                    billing_plan: 'paid',
                    products: expect.arrayContaining([
                        expect.objectContaining({
                            type: 'product_analytics',
                            name: 'Product Analytics',
                        }),
                    ]),
                }),
            })
        })
    })
})

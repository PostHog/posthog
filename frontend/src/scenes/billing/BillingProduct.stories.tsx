import { Meta, StoryObj } from '@storybook/react'
import { within } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { makeBillingWithPlatformAddons } from '~/mocks/fixtures/_billing_platform_addons'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { BillingProductV2Type, BillingType, StartupProgramLabel } from '~/types'

import { POSTHOG_CODE_BILLING_LIMIT_MAX, POSTHOG_CODE_USAGE_PRODUCT_KEY } from './billingLimitConfig'
import { BillingProduct } from './BillingProduct'

const meta: Meta = {
    title: 'Scenes-Other/Billing Product',
    parameters: {
        layout: 'padded',
        viewMode: 'story',
        mockDate: '2024-03-10',
    },
    decorators: [
        mswDecorator({
            get: {
                '/_preflight': {
                    ...preflightJson,
                    cloud: true,
                    realm: 'cloud',
                },
            },
        }),
    ],
}
export default meta

type Story = StoryObj<{}>

const BillingProductStoryFrame = ({ children }: { children: JSX.Element }): JSX.Element => (
    <div className="w-[960px] max-w-full">{children}</div>
)

const makePostHogCodeUsageBilling = ({
    currentLimitUsd,
    nextPeriodLimitUsd,
}: {
    currentLimitUsd: number
    nextPeriodLimitUsd?: number
}): { billing: BillingType; product: BillingProductV2Type } => {
    const sourceProduct = billingJson.products.find(
        (product) => product.type === 'feature_flags'
    ) as BillingProductV2Type
    const product: BillingProductV2Type = {
        ...sourceProduct,
        name: 'PostHog Code',
        headline: 'AI coding agents for your PostHog workspace.',
        description: 'AI coding agents for automating PostHog work.',
        usage_key: POSTHOG_CODE_USAGE_PRODUCT_KEY,
        icon_key: 'IconTerminal',
        docs_url: 'https://posthog.com/docs/posthog-code',
        subscribed: true,
        type: POSTHOG_CODE_USAGE_PRODUCT_KEY,
        current_amount_usd: currentLimitUsd > POSTHOG_CODE_BILLING_LIMIT_MAX ? '3750.00' : '25.00',
        projected_amount_usd: currentLimitUsd > POSTHOG_CODE_BILLING_LIMIT_MAX ? '4100.00' : '75.00',
        projected_amount_usd_with_limit: currentLimitUsd > POSTHOG_CODE_BILLING_LIMIT_MAX ? '3750.00' : '75.00',
        plans: sourceProduct.plans.map((plan) => ({
            ...plan,
            initial_billing_limit: 50,
        })),
    }
    const nextPeriodLimits: Record<string, number | null> =
        nextPeriodLimitUsd === undefined ? {} : { [POSTHOG_CODE_USAGE_PRODUCT_KEY]: nextPeriodLimitUsd }

    return {
        product,
        billing: {
            ...billingJson,
            startup_program_label: StartupProgramLabel.Startup,
            products: [product],
            custom_limits_usd: {
                [POSTHOG_CODE_USAGE_PRODUCT_KEY]: currentLimitUsd,
            },
            next_period_custom_limits_usd: nextPeriodLimits,
        },
    }
}

const renderPostHogCodeUsageBillingProduct = ({
    currentLimitUsd,
    nextPeriodLimitUsd,
}: {
    currentLimitUsd: number
    nextPeriodLimitUsd?: number
}): JSX.Element => {
    const { billing, product } = makePostHogCodeUsageBilling({ currentLimitUsd, nextPeriodLimitUsd })

    useStorybookMocks({
        get: {
            '/api/billing/': billing,
        },
    })

    return (
        <BillingProductStoryFrame>
            <BillingProduct product={product} />
        </BillingProductStoryFrame>
    )
}

export const BillingProductWithoutAddons: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        const product = billingJson.products.find((product) => product.type === 'feature_flags')

        return <BillingProduct product={product as BillingProductV2Type} />
    },
}

export const BillingProductWithAddons: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        const product = billingJson.products.find((product) => product.type === 'product_analytics')

        return <BillingProduct product={product as BillingProductV2Type} />
    },
}

export const BillingProductWithStandalonePricingAddon: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        const product = billingJson.products.find((product) => product.type === 'session_replay')

        return <BillingProduct product={product as BillingProductV2Type} />
    },
}

export const BillingProductPostHogCodeLimit: Story = {
    render: () =>
        renderPostHogCodeUsageBillingProduct({
            currentLimitUsd: 50,
        }),
}

export const BillingProductPostHogCodeLimitEditing: Story = {
    render: () =>
        renderPostHogCodeUsageBillingProduct({
            currentLimitUsd: 50,
        }),
    play: async ({ canvasElement }) => {
        const canvas = within(canvasElement)
        await userEvent.click(await canvas.findByText('Edit limit'))
    },
}

export const BillingProductPostHogCodeLimitNextPeriodCapped: Story = {
    render: () =>
        renderPostHogCodeUsageBillingProduct({
            currentLimitUsd: 3750,
            nextPeriodLimitUsd: 3000,
        }),
}

export const BillingProductTemporarilyFree: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        const product = {
            name: 'Data Warehouse',
            headline: 'A single source for all your data.',
            description: 'Import external data and query it alongside your analytics data.',
            price_description: null,
            usage_key: 'rows_synced',
            image_url: 'https://posthog.com/images/product/product-icons/data-warehouse.svg',
            screenshot_url: null,
            icon_key: 'IconBuilding',
            docs_url: 'https://posthog.com/docs/data-warehouse',
            subscribed: false,
            plans: [
                {
                    plan_key: 'free-20240530-beta-users-initial',
                    product_key: 'data_warehouse',
                    name: 'Free (beta)',
                    description: 'Import external data and query it alongside your analytics data.',
                    image_url: 'https://posthog.com/images/product/product-icons/data-warehouse.svg',
                    docs_url: 'https://posthog.com/docs/data-warehouse',
                    note: null,
                    unit: 'row',
                    flat_rate: false,
                    free_allocation: null,
                    features: [
                        {
                            key: 'data_warehouse_integrations',
                            name: 'One-click integrations',
                            description: 'Sync data from Stripe, Hubspot, Zendesk, Snowflake, Postgres, and more.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                        {
                            key: 'data_warehouse_views',
                            name: 'Custom views',
                            description: 'Create views to model your data and streamline queries.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                        {
                            key: 'data_warehouse_direct_linking',
                            name: 'Direct linking',
                            description:
                                'Link directly to your data sources such as S3, Google Cloud Storage, and Cloudflare R2. Data stays on your servers.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                        {
                            key: 'data_warehouse_joins',
                            name: 'Cross-source joins',
                            description:
                                'Join data from any source, including your PostHog analytics data, to easily get the answers you need.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                        {
                            key: 'data_warehouse_unified_querying',
                            name: 'Unified querying',
                            description: 'Query all your business and product data directly inside PostHog.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                        {
                            key: 'data_warehouse_insights_visualization',
                            name: 'Data visualization',
                            description:
                                'Create insights from the data you import and add them to your PostHog dashboards.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                        {
                            key: 'data_warehouse_incremental_sync',
                            name: 'Incremental sync',
                            description: 'Sync only the data that has changed since the last sync.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                        {
                            key: 'data_warehouse_sync_frequency',
                            name: 'Sync frequency',
                            description: 'Choose how often you want to sync your data - daily, weekly, or monthly.',
                            unit: null,
                            limit: null,
                            note: null,
                            is_plan_default: true,
                        },
                    ],
                    tiers: null,
                    current_plan: true,
                    included_if: null,
                    contact_support: null,
                    unit_amount_usd: null,
                    initial_billing_limit: null,
                },
            ],
            type: 'data_warehouse',
            free_allocation: 0,
            tiers: null,
            tiered: false,
            unit_amount_usd: null,
            current_amount_usd_before_addons: null,
            current_amount_usd: null,
            current_usage: 2345,
            usage_limit: 0,
            has_exceeded_limit: false,
            percentage_usage: 0,
            projected_usage: 76723,
            projected_amount_usd: null,
            projected_amount_usd_with_limit: null,
            unit: 'row',
            display_unit: null,
            display_decimals: null,
            display_divisor: null,
            addons: [],
            contact_support: false,
            inclusion_only: false,
            features: [
                {
                    key: 'data_warehouse_integrations',
                    name: 'One-click integrations',
                    description: 'Sync data from Stripe, Hubspot, Zendesk, Snowflake, Postgres, and more.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
                {
                    key: 'data_warehouse_direct_linking',
                    name: 'Direct linking',
                    description:
                        'Link directly to your data sources such as S3, Google Cloud Storage, and Cloudflare R2. Data stays on your servers.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
                {
                    key: 'data_warehouse_views',
                    name: 'Custom views',
                    description: 'Create views to model your data and streamline queries.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
                {
                    key: 'data_warehouse_joins',
                    name: 'Cross-source joins',
                    description:
                        'Join data from any source, including your PostHog analytics data, to easily get the answers you need.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
                {
                    key: 'data_warehouse_unified_querying',
                    name: 'Unified querying',
                    description: 'Query all your business and product data directly inside PostHog.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
                {
                    key: 'data_warehouse_insights_visualization',
                    name: 'Data visualization',
                    description: 'Create insights from the data you import and add them to your PostHog dashboards.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
                {
                    key: 'data_warehouse_incremental_sync',
                    name: 'Incremental sync',
                    description: 'Sync only the data that has changed since the last sync.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
                {
                    key: 'data_warehouse_sync_frequency',
                    name: 'Sync frequency',
                    description: 'Choose how often you want to sync your data - daily, weekly, or monthly.',
                    images: null,
                    icon_key: null,
                    type: null,
                },
            ],
        }

        return <BillingProduct product={product as BillingProductV2Type} />
    },
}

export const BillingProductInclusionOnlyWithAddon: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        const product = billingJson.products.find((product) => product.type === 'platform_and_support')

        return <BillingProduct product={product as BillingProductV2Type} />
    },
}

const renderPlatformAddonsStory = (scenario: Parameters<typeof makeBillingWithPlatformAddons>[1]): JSX.Element => {
    const billing = makeBillingWithPlatformAddons(billingJson, scenario)
    useStorybookMocks({
        get: {
            '/api/billing/': billing,
        },
    })
    const product = billing.products.find((p) => p.type === 'platform_and_support')
    return <BillingProduct product={product as BillingProductV2Type} />
}

export const BillingProductPlatformAddonsTrialAvailable: Story = {
    render: () => renderPlatformAddonsStory('trial-available'),
}

export const BillingProductPlatformAddonsTrialUsed: Story = {
    render: () => renderPlatformAddonsStory('trial-used'),
}

export const BillingProductPlatformAddonsOnScale: Story = {
    render: () => renderPlatformAddonsStory('on-scale'),
}

export const BillingProductPlatformAddonsOnLegacyTeams: Story = {
    render: () => renderPlatformAddonsStory('on-legacy-teams'),
}

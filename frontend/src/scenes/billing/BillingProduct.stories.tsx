import { Meta } from '@storybook/react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { BillingProductV2Type } from '~/types'

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

export const BillingProductWithoutAddons = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })

    const product = billingJson.products.find((product) => product.type === 'feature_flags')

    return <BillingProduct product={product as BillingProductV2Type} />
}

export const BillingProductWithAddons = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })

    const product = billingJson.products.find((product) => product.type === 'product_analytics')

    return <BillingProduct product={product as BillingProductV2Type} />
}

export const BillingProductWithStandalonePricingAddon = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })

    const product = billingJson.products.find((product) => product.type === 'session_replay')

    return <BillingProduct product={product as BillingProductV2Type} />
}

export const BillingProductTemporarilyFree = (): JSX.Element => {
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
}

export const BillingProductInclusionOnlyWithAddon = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })

    const product = billingJson.products.find((product) => product.type === 'platform_and_support')

    return <BillingProduct product={product as BillingProductV2Type} />
}

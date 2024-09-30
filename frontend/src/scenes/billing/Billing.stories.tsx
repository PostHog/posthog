import { Meta } from '@storybook/react'
import { FEATURE_FLAGS } from 'lib/constants'

import { mswDecorator, setFeatureFlags, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import billingJsonWith100PercentDiscount from '~/mocks/fixtures/_billing_with_100_percent_discount.json'
import billingJsonWithDiscount from '~/mocks/fixtures/_billing_with_discount.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import batchExports from '~/mocks/fixtures/api/organizations/@current/batchExports.json'
import exportsUnsubscribeConfigs from '~/mocks/fixtures/api/organizations/@current/plugins/exportsUnsubscribeConfigs.json'

import { Billing } from './Billing'
import { PurchaseCreditsModal } from './PurchaseCreditsModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

const meta: Meta = {
    title: 'Scenes-Other/Billing',
    parameters: {
        layout: 'fullscreen',
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
export const _Billing = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })

    return <Billing />
}

export const BillingWithDiscount = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJsonWithDiscount,
            },
        },
    })

    return <Billing />
}

export const BillingWithCreditCTA = (): JSX.Element => {
    setFeatureFlags([FEATURE_FLAGS.PURCHASE_CREDITS])
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
            '/api/billing/credits/overview': {
                status: 'none',
                eligible: true,
                estimated_monthly_credit_amount_usd: 1200,
                email: 'test@posthog.com',
                cc_last_four: '1234',
                cc_brand: 'Visa',
            },
        },
    })

    return <Billing />
}

export const BillingWithLimitAnd100PercentDiscount = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJsonWith100PercentDiscount,
            },
        },
    })

    return <Billing />
}

export const BillingPurchaseCreditsModal = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
            '/api/billing/credits/overview': {
                status: 'none',
                eligible: true,
                estimated_monthly_credit_amount_usd: 1200,
                email: 'test@posthog.com',
                cc_last_four: '1234',
                cc_brand: 'Visa',
            },
        },
    })

    return <PurchaseCreditsModal />
}

export const BillingUnsubscribeModal = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
        },
    })

    return <UnsubscribeSurveyModal product={billingJson.products[0]} />
}
export const BillingUnsubscribeModal_DataPipelines = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
            },
            '/api/organizations/@current/plugins/exports_unsubscribe_configs/': exportsUnsubscribeConfigs,
            '/api/organizations/@current/batch_exports': batchExports,
            '/api/organizations/@current/': {
                ...organizationCurrent,
            },
        },
    })
    const product = billingJson.products[0]
    product.addons = [
        {
            type: 'data_pipelines',
            subscribed: true,
            name: 'Data Pipelines',
            description: 'Add-on description',
            price_description: 'Add-on price description',
            image_url: 'Add-on image URL',
            docs_url: 'Add-on documentation URL',
            tiers: [],
            tiered: false,
            unit: '',
            unit_amount_usd: '0',
            current_amount_usd: '0',
            current_usage: 0,
            projected_usage: 0,
            projected_amount_usd: '0',
            plans: [],
            usage_key: '',
            contact_support: false,
            inclusion_only: false,
            features: [],
        },
    ]

    return <UnsubscribeSurveyModal product={product} />
}
BillingUnsubscribeModal_DataPipelines.parameters = {
    testOptions: { waitForSelector: '.LemonTable__content' },
}

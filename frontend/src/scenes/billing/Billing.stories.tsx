import { Meta } from '@storybook/react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing_v2'
import billingJsonWith100PercentDiscount from '~/mocks/fixtures/_billing_v2_with_100_percent_discount.json'
import billingJsonWithDiscount from '~/mocks/fixtures/_billing_v2_with_discount.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import organizationCurrent from '~/mocks/fixtures/api/organizations/@current/@current.json'
import batchExports from '~/mocks/fixtures/api/organizations/@current/batchExports.json'
import exportsUnsubscribeConfigs from '~/mocks/fixtures/api/organizations/@current/plugins/exportsUnsubscribeConfigs.json'
import organizationPlugins from '~/mocks/fixtures/api/organizations/@current/plugins/plugins.json'

import { Billing } from './Billing'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

const meta: Meta = {
    title: 'Scenes-Other/Billing v2',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2023-05-25',
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
export const _BillingV2 = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJson,
            },
        },
    })

    return <Billing />
}

export const BillingV2WithDiscount = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJsonWithDiscount,
            },
        },
    })

    return <Billing />
}

export const BillingV2WithLimitAnd100PercentDiscount = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJsonWith100PercentDiscount,
            },
        },
    })

    return <Billing />
}

export const BillingUnsubscribeModal = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJson,
            },
        },
    })

    return <UnsubscribeSurveyModal product={billingJson.products[0]} />
}
export const BillingUnsubscribeModal_DataPipelines = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing-v2/': {
                ...billingJson,
            },
            '/api/organizations/@current/plugins/exports_unsubscribe_configs/': exportsUnsubscribeConfigs,
            '/api/organizations/@current/batch_exports': batchExports,
            '/api/organizations/@current/plugins': {
                ...organizationPlugins,
            },
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
        },
    ]

    return <UnsubscribeSurveyModal product={product} />
}
BillingUnsubscribeModal_DataPipelines.parameters = {
    testOptions: { waitForSelector: '.LemonTable__content' },
}

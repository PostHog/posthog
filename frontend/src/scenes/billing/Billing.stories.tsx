import { Meta } from '@storybook/react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import billingJsonWith100PercentDiscount from '~/mocks/fixtures/_billing_with_100_percent_discount.json'
import billingJsonWithCredits from '~/mocks/fixtures/_billing_with_credits.json'
import billingJsonWithDiscount from '~/mocks/fixtures/_billing_with_discount.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { Billing } from './Billing'
import { PurchaseCreditsModal } from './PurchaseCreditsModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

const meta: Meta = {
    title: 'Scenes-Other/Billing',
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2024-03-10',
        testOptions: {
            // Needs a slightly larger width to push the rendered scene away from breakpoint boundary
            viewport: {
                width: 1300,
                height: 720,
            },
        },
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

export const BillingWithCredits = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJsonWithCredits,
            },
        },
    })

    return <Billing />
}

export const BillingWithCreditCTA = (): JSX.Element => {
    useStorybookMocks({
        get: {
            '/api/billing/': {
                ...billingJson,
                account_owner: null,
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
                credit_brackets: [
                    { discount: 0.1, annual_credit_from_inclusive: 3333, annual_credit_to_exclusive: 25000 },
                    { discount: 0.2, annual_credit_from_inclusive: 25000, annual_credit_to_exclusive: 80000 },
                    { discount: 0.25, annual_credit_from_inclusive: 80000, annual_credit_to_exclusive: 153847 },
                    { discount: 0.35, annual_credit_from_inclusive: 153847, annual_credit_to_exclusive: null },
                ],
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

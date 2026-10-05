import { Meta, StoryObj } from '@storybook/react'

import { mswDecorator, useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { billingUnsubscribedJson } from '~/mocks/fixtures/_billing_unsubscribed'
import billingJsonWith100PercentDiscount from '~/mocks/fixtures/_billing_with_100_percent_discount.json'
import billingJsonWithCredits from '~/mocks/fixtures/_billing_with_credits.json'
import billingJsonWithDiscount from '~/mocks/fixtures/_billing_with_discount.json'
import preflightJson from '~/mocks/fixtures/_preflight.json'
import { BillingType, StartupProgramLabel } from '~/types'

import { Billing } from './Billing'
import { PurchaseCreditsModal } from './PurchaseCreditsModal'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

const BILLING_LIMIT_FIELDS = new Set(['custom_limits_usd', 'next_period_custom_limits_usd'])
const BILLING_MONEY_FIELDS = new Set([
    'amount_off_expires_at',
    'discount_percent',
    'external_billing_provider_invoices_url',
    'price_description',
    'projected_amount',
    'stripe_portal_url',
    'tiers',
])

// What the billing API answers while a partner pays: every amount and price is null, limits and usage stay.
const withoutMoney = <T,>(value: T): T => {
    if (Array.isArray(value)) {
        return value.map(withoutMoney) as T
    }
    if (value === null || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype) {
        return value
    }
    return Object.fromEntries(
        Object.entries(value).map(([field, fieldValue]) => [
            field,
            BILLING_MONEY_FIELDS.has(field) || (field.split('_').includes('usd') && !BILLING_LIMIT_FIELDS.has(field))
                ? null
                : withoutMoney(fieldValue),
        ])
    ) as T
}

const partnerPaidBilling = (billing: BillingType): BillingType =>
    withoutMoney({
        ...billing,
        customer_id: '',
        billing_managed_by_partner: { partner_name: 'Example Partner' },
    })

// Mirrors prod payloads where the billing API omits icon_key — exercises the productType fallback
// in getProductIcon so each product still renders its own icon.
const billingJsonWithoutIconKeys: BillingType = {
    ...billingJson,
    products: billingJson.products.map((product) => ({
        ...product,
        icon_key: null,
        addons: product.addons.map((addon) => ({ ...addon, icon_key: undefined })),
    })),
}

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

type Story = StoryObj<{}>

export const _Billing: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        return <Billing />
    },
}

export const BillingManagedByPartner: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': partnerPaidBilling(billingUnsubscribedJson),
            },
        })

        return <Billing />
    },
}

export const BillingManagedByPartnerOnPaidPlan: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': partnerPaidBilling({ ...billingJson, custom_limits_usd: { product_analytics: 500 } }),
            },
        })

        return <Billing />
    },
}

export const BillingOnStartupPlan: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                    startup_program_label: StartupProgramLabel.Startup,
                },
            },
        })

        return <Billing />
    },
}

export const BillingWithDiscount: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJsonWithDiscount,
                },
            },
        })

        return <Billing />
    },
}

export const BillingWithCredits: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJsonWithCredits,
                },
            },
        })

        return <Billing />
    },
}

export const BillingWithCreditCTA: Story = {
    render: () => {
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
    },
}

export const BillingWithLimitAnd100PercentDiscount: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJsonWith100PercentDiscount,
                },
            },
        })

        return <Billing />
    },
}

export const BillingPurchaseCreditsModal: Story = {
    render: () => {
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
    },
}

export const BillingWithoutIconKeys: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJsonWithoutIconKeys,
                },
            },
        })

        return <Billing />
    },
}

export const BillingUnsubscribeModal: Story = {
    render: () => {
        useStorybookMocks({
            get: {
                '/api/billing/': {
                    ...billingJson,
                },
            },
        })

        return <UnsubscribeSurveyModal product={billingJson.products[0]} />
    },
}

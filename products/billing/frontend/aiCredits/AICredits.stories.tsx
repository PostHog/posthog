import { Meta, StoryObj } from '@storybook/react'
import { useActions } from 'kea'
import { useEffect } from 'react'

import { mswDecorator } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import preflightJson from '~/mocks/fixtures/_preflight.json'

import { AICredits } from './AICredits'
import { aiCreditsLogic } from './aiCreditsLogic'

const RELOAD_ON = {
    monthly_spend_limit_usd: '500.00',
    low_balance_threshold_usd: '20.00',
    automatic_reload: {
        enabled: true,
        target_usd: '100.00',
        monthly_reload_limit_usd: '300.00',
        disabled_reason: null,
        disabled_at: null,
    },
}

const RELOAD_OFF_AFTER_DECLINE = {
    monthly_spend_limit_usd: null,
    low_balance_threshold_usd: '20.00',
    automatic_reload: {
        enabled: false,
        target_usd: '100.00',
        monthly_reload_limit_usd: null,
        disabled_reason: 'card_declined',
        disabled_at: '2026-11-02T09:30:00Z',
    },
}

const HISTORY = {
    has_more: false,
    results: [
        {
            created_at: '2026-11-02T10:14:00Z',
            kind: 'purchase',
            amount_usd: '50.00',
            tax_usd: '4.13',
            total_usd: '54.13',
            status: 'pending',
            receipt_url: 'https://pay.stripe.com/receipts/example-1',
        },
        {
            created_at: '2026-10-30T03:41:00Z',
            kind: 'automatic_reload',
            amount_usd: '80.00',
            tax_usd: '6.60',
            total_usd: '86.60',
            status: 'added',
            receipt_url: 'https://pay.stripe.com/receipts/example-2',
        },
    ],
}

function mocks(settings: Record<string, unknown>): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/_preflight': { ...preflightJson, cloud: true, realm: 'cloud' },
            '/api/billing/': { ...billingJson, stripe_portal_url: 'https://billing.stripe.com/p/session/example' },
            '/api/billing/ai_credits/settings/': settings,
            '/api/billing/ai_credits/card/': { card: { brand: 'visa', last4: '4242', exp_month: 8, exp_year: 2030 } },
            '/api/billing/ai_credits/history/': HISTORY,
            '/api/billing/ai_credits/quote/': { amount_usd: '50.00', tax_usd: '4.13', total_usd: '54.13' },
        },
    })
}

const meta: Meta = {
    title: 'Scenes-Other/Billing/AI credits',
    component: AICredits,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-11-03' },
}
export default meta

type Story = StoryObj<typeof AICredits>

export const ReloadOn: Story = { decorators: [mocks(RELOAD_ON)] }

export const ReloadOffAfterADecline: Story = { decorators: [mocks(RELOAD_OFF_AFTER_DECLINE)] }

function AICreditsWithAddFundsOpen(): JSX.Element {
    const { openAddFundsModal } = useActions(aiCreditsLogic)
    useEffect(() => openAddFundsModal(), [openAddFundsModal])
    return <AICredits />
}

export const AddFunds: Story = {
    decorators: [mocks(RELOAD_OFF_AFTER_DECLINE)],
    render: () => <AICreditsWithAddFundsOpen />,
}

import type { Meta, StoryObj } from '@storybook/react'

import { useStorybookMocks } from '~/mocks/browser'
import { billingJson } from '~/mocks/fixtures/_billing'
import { BillingProductV2Type, BillingType } from '~/types'

import { InboxUsageWidget } from './InboxUsageWidget'

// Drives the inbox PR-usage widget purely off the billing payload: one `inbox` product whose
// tiers / usage / limit place the run in a given state. `display_divisor: 1` keeps credits == PRs so
// the numbers read directly; `current_usage` drives the bar.
const PRICE_PER_PR = 2

interface InboxState {
    subscribed: boolean
    freePrs: number
    usedPrs: number
    limitPrs: number | null
}

function inboxProduct({ subscribed, freePrs, usedPrs, limitPrs }: InboxState): BillingProductV2Type {
    const base = billingJson.products[0]
    const tierTemplate = base.tiers?.[0]
    return {
        ...base,
        type: 'inbox',
        name: 'Inbox',
        usage_key: 'signals_credits',
        subscribed,
        display_divisor: 1,
        free_allocation: subscribed ? 0 : freePrs,
        current_usage: usedPrs,
        usage_limit: limitPrs,
        unit_amount_usd: PRICE_PER_PR.toFixed(2),
        tiers: tierTemplate
            ? [
                  { ...tierTemplate, up_to: freePrs, unit_amount_usd: '0' },
                  { ...tierTemplate, up_to: null, unit_amount_usd: PRICE_PER_PR.toFixed(2) },
              ]
            : null,
    }
}

function billingFor(state: InboxState): BillingType {
    return { ...billingJson, products: [inboxProduct(state)], custom_limits_usd: {} }
}

function StateMocks({ state }: { state: InboxState }): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/billing/': billingFor(state),
        },
    })
    // Mimic the agents rail's narrow column so the widget lays out as it does in the scene.
    return (
        <div className="w-[260px] p-4 bg-surface-secondary">
            <InboxUsageWidget />
        </div>
    )
}

const meta: Meta = {
    title: 'Scenes-App/Inbox/UsageWidget',
    component: InboxUsageWidget,
    parameters: {
        layout: 'centered',
        viewMode: 'story',
        mockDate: '2024-03-20',
    },
}
export default meta

type Story = StoryObj

export const FreePlanZeroUsage: Story = {
    render: () => <StateMocks state={{ subscribed: false, freePrs: 3, usedPrs: 0, limitPrs: 3 }} />,
}

export const WithinFreeTier: Story = {
    render: () => <StateMocks state={{ subscribed: true, freePrs: 3, usedPrs: 2, limitPrs: 50 }} />,
}

export const BillableUsage: Story = {
    render: () => <StateMocks state={{ subscribed: true, freePrs: 3, usedPrs: 12, limitPrs: 50 }} />,
}

export const ApproachingLimit: Story = {
    render: () => <StateMocks state={{ subscribed: true, freePrs: 3, usedPrs: 42, limitPrs: 50 }} />,
}

export const AtLimit: Story = {
    render: () => <StateMocks state={{ subscribed: true, freePrs: 3, usedPrs: 50, limitPrs: 50 }} />,
}

import { Meta, StoryObj } from '@storybook/react'
import { screen } from '@testing-library/dom'
import userEvent from '@testing-library/user-event'

import billingJsonWithBillingLimits from '~/mocks/fixtures/_billing_with_billing_limits.json'
import { BillingProductV2Type, BillingType } from '~/types'

import { createGaugeItems } from './billing-utils'
import { BillingGauge } from './BillingGauge'

// These stories render the usage gauge in isolation so the bar treatments (and their hover
// tooltips) are easy to review without the noise of the whole billing page.
//
// Everything is derived from the real `_billing_with_billing_limits.json` demo payload rather than
// hand-picked numbers: product analytics there has a $500 billing limit, which the API maps to a
// usage limit of ~3.46M events (well above the 1M free tier — a limit can never sit below the free
// tier). Each scenario only varies current/projected usage within valid ranges; the tiers, pricing
// and limit stay real, so "what you'll pay" tooltips show genuine amounts.
const billing = billingJsonWithBillingLimits as unknown as BillingType
const productAnalytics = billing.products.find(
    (product) => product.type === 'product_analytics'
) as BillingProductV2Type
const USAGE_LIMIT = productAnalytics.usage_limit ?? 0

function GaugeDemo({ currentUsage, projectedUsage }: { currentUsage: number; projectedUsage: number }): JSX.Element {
    const product: BillingProductV2Type = {
        ...productAnalytics,
        current_usage: currentUsage,
        projected_usage: projectedUsage,
        percentage_usage: USAGE_LIMIT ? currentUsage / USAGE_LIMIT : 0,
    }
    const items = createGaugeItems(product, { billing, billingLimitAsUsage: USAGE_LIMIT })
    return (
        <div className="w-[900px] p-8">
            <BillingGauge items={items} product={product} billing={billing} />
        </div>
    )
}

// The section tooltips render into a portal on document.body, so we query via `screen` (global)
// rather than the story canvas. Awaiting the tooltip copy both proves it opened and holds the
// snapshot until it's on screen.
async function hoverSectionAndWaitForTooltip(selector: string, tooltipText: RegExp): Promise<void> {
    const section = document.querySelector(selector)
    if (!section) {
        throw new Error(`Could not find gauge section "${selector}"`)
    }
    await userEvent.hover(section)
    await screen.findByText(tooltipText, undefined, { timeout: 3000 })
}

const meta: Meta<typeof BillingGauge> = {
    title: 'Scenes-Other/Billing/BillingGauge',
    component: BillingGauge,
}
export default meta

type Story = StoryObj<typeof BillingGauge>

// Current and projected both below the limit: solid blue usage, blue forecast stripes, and the free
// tier + billing limit tick markers all sit apart.
export const WithinLimit: Story = {
    render: () => <GaugeDemo currentUsage={1_800_000} projectedUsage={2_900_000} />,
}

// Current below the limit but forecast to blow past it: the forecast stripes carry on past the
// billing limit marker, so the overshoot is obvious.
export const ForecastExceedsLimit: Story = {
    render: () => <GaugeDemo currentUsage={1_800_000} projectedUsage={4_500_000} />,
}

// The full mix: usage is already over the limit (solid blue up to the limit, desaturated grey
// stripes above it), with the forecast layered on top in the opposite-angle stripes.
export const UsageExceedsLimit: Story = {
    render: () => <GaugeDemo currentUsage={4_200_000} projectedUsage={4_900_000} />,
}

export const UsageExceedsLimitPaidHovered: Story = {
    render: () => <GaugeDemo currentUsage={4_200_000} projectedUsage={4_900_000} />,
    play: async () => {
        await hoverSectionAndWaitForTooltip(
            '.BillingGaugeItem__section--paid',
            /What you'll pay for Product analytics/i
        )
    },
}

export const UsageExceedsLimitOverLimitHovered: Story = {
    render: () => <GaugeDemo currentUsage={4_200_000} projectedUsage={4_900_000} />,
    play: async () => {
        await hoverSectionAndWaitForTooltip(
            '.BillingGaugeItem__section--over-limit',
            /won't be charged for usage above your billing limit/i
        )
    },
}

export const UsageExceedsLimitForecastHovered: Story = {
    render: () => <GaugeDemo currentUsage={4_200_000} projectedUsage={4_900_000} />,
    play: async () => {
        await hoverSectionAndWaitForTooltip(
            '.BillingGaugeItem--projected_usage .BillingGaugeItem__section',
            /Projected usage by the end/i
        )
    },
}

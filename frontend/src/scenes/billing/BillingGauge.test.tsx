import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { BillingProductV2Type } from '~/types'

import { BillingGauge } from './BillingGauge'
import { BillingGaugeItemKind, BillingGaugeItemType } from './types'

const makeProduct = (overrides: Partial<BillingProductV2Type> = {}): BillingProductV2Type =>
    ({
        type: 'product_analytics',
        tiers: [{ up_to: null, unit_amount_usd: '0.5', flat_amount_usd: '0', current_amount_usd: '0' }],
        percentage_usage: 0,
        ...overrides,
    }) as BillingProductV2Type

const usageItems = (current: number, limit: number): BillingGaugeItemType[] => [
    { type: BillingGaugeItemKind.BillingLimit, text: 'Billing limit', value: limit },
    { type: BillingGaugeItemKind.CurrentUsage, text: 'Current', value: current },
]

describe('BillingGauge', () => {
    afterEach(cleanup)

    it('splits the current usage bar at the billing limit when over it', () => {
        // usage 8 over a limit of 3 -> paid section covers 3/8 = 37.5% of the bar, rest is not charged
        const { container } = render(
            <BillingGauge items={usageItems(8, 3)} product={makeProduct({ percentage_usage: 8 / 3 })} />
        )

        const paid = container.querySelector<HTMLElement>('.BillingGaugeItem__section--paid')
        const overLimit = container.querySelector<HTMLElement>('.BillingGaugeItem__section--over-limit')

        expect(paid).toBeInTheDocument()
        expect(overLimit).toBeInTheDocument()
        expect(paid?.style.width).toBe('37.5%')
        expect(overLimit?.style.left).toBe('37.5%')
    })

    it('confines the projected forecast hover to the span beyond current usage', () => {
        // projected 16 over current 8 -> forecast section starts at 8/16 = 50%, leaving the paid/
        // over-limit sections (0..current) reachable underneath instead of occluded by a full overlay.
        const items: BillingGaugeItemType[] = [
            ...usageItems(8, 3),
            { type: BillingGaugeItemKind.ProjectedUsage, text: 'Projected', value: 16 },
        ]
        const { container } = render(
            <BillingGauge items={items} product={makeProduct({ current_usage: 8, percentage_usage: 8 / 3 })} />
        )

        const forecast = container.querySelector<HTMLElement>(
            '.BillingGaugeItem--projected_usage .BillingGaugeItem__section'
        )
        expect(forecast?.style.left).toBe('50%')
    })

    it('does not split the bar when usage is below the billing limit', () => {
        const { container } = render(
            <BillingGauge items={usageItems(2, 3)} product={makeProduct({ percentage_usage: 2 / 3 })} />
        )

        expect(container.querySelector('.BillingGaugeItem__section--paid')).not.toBeInTheDocument()
        expect(container.querySelector('.BillingGaugeItem__section--over-limit')).not.toBeInTheDocument()
    })

    it('does not split the monetary ($) gauge even when over the limit', () => {
        const items: BillingGaugeItemType[] = [
            { type: BillingGaugeItemKind.BillingLimit, text: 'Billing limit', value: 3, prefix: '$' },
            { type: BillingGaugeItemKind.CurrentUsage, text: 'Current', value: 8, prefix: '$' },
        ]
        const { container } = render(
            <BillingGauge items={items} product={makeProduct({ unit: '$', percentage_usage: 8 / 3 })} />
        )

        expect(container.querySelector('.BillingGaugeItem__section--paid')).not.toBeInTheDocument()
    })
})

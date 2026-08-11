import { Meta, StoryObj } from '@storybook/react'

import { dayjs } from 'lib/dayjs'

import { BillingLineGraph, type BillingSeriesType } from './BillingLineGraph'

const DATES = Array.from({ length: 30 }, (_, i) => dayjs.utc('2024-02-15').add(i, 'day').format('YYYY-MM-DD'))

const seriesFrom = (id: number, label: string, base: number, amplitude: number): BillingSeriesType => ({
    id,
    label,
    dates: DATES,
    // Deterministic wave so the story stays screenshot-stable.
    data: DATES.map((_, i) => Math.round(base + amplitude * Math.sin(i / 3))),
})

const SERIES: BillingSeriesType[] = [
    seriesFrom(0, 'Product analytics', 1_200_000, 400_000),
    seriesFrom(1, 'Session replay', 480_000, 120_000),
    seriesFrom(2, 'Feature flags', 90_000, 30_000),
]

const meta: Meta<typeof BillingLineGraph> = {
    title: 'Scenes-Other/Billing/BillingLineGraph',
    component: BillingLineGraph,
    parameters: { layout: 'padded' },
    // The chart sizes itself from its container via ResizeObserver, so the wrapper needs a definite
    // width — the snapshot runtime shrink-wraps the story root, which squeezes the plot to a few
    // hundred pixels and drops most of the x-axis ticks.
    decorators: [
        (Story) => (
            <div className="w-[960px]">
                <Story />
            </div>
        ),
    ],
    // `showLegend: false` mirrors both callers (BillingUsage, BillingSpendView). Left at the
    // component default these snapshots would guard a legend the app never renders.
    args: { series: SERIES, dates: DATES, hiddenSeries: [], showLegend: false },
}
export default meta

type Story = StoryObj<typeof BillingLineGraph>

/**
 * Only two stories, both with a marker: a screenshot's one advantage over BillingLineGraph.test.tsx
 * is showing whether the label clears the plot and survives the wrapper's `overflow: hidden`.
 */
export const WithBillingPeriodMarker: Story = {
    args: { billingPeriodMarkers: [{ date: dayjs.utc('2024-03-01') }] },
}

/** A period starting on the first plotted bucket, where the label overhangs the y-axis edge. */
export const WithMarkerAtRangeStart: Story = {
    args: { billingPeriodMarkers: [{ date: dayjs.utc(DATES[0]) }] },
}

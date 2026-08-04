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
    parameters: { layout: 'padded', testOptions: { viewport: { width: 1000, height: 500 } } },
    args: { series: SERIES, dates: DATES, hiddenSeries: [] },
}
export default meta

type Story = StoryObj<typeof BillingLineGraph>

export const Default: Story = {}

export const WithBillingPeriodMarker: Story = {
    args: { billingPeriodMarkers: [{ date: dayjs.utc('2024-03-01') }] },
}

export const AsSpend: Story = {
    args: {
        series: [seriesFrom(0, 'Product analytics', 420, 160), seriesFrom(1, 'Session replay', 130, 40)],
        valueFormatter: (value: number) => `$${value.toLocaleString()}`,
        billingPeriodMarkers: [{ date: dayjs.utc('2024-03-01') }],
    },
}

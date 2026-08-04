import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { ensureJsdom, getHogChart } from '@posthog/quill-charts/testing'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { BillingLineGraph, type BillingSeriesType } from './BillingLineGraph'

const DATES = ['2026-01-01', '2026-01-02', '2026-01-03']

const SERIES: BillingSeriesType[] = [
    { id: 0, label: 'Events', data: [10, 20, 30], dates: DATES },
    { id: 1, label: 'Recordings', data: [1, 2, 3], dates: DATES },
]

describe('BillingLineGraph', () => {
    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders only the series that are not hidden', async () => {
        render(<BillingLineGraph series={SERIES} dates={DATES} hiddenSeries={[1]} />)

        await waitFor(() => expect(getHogChart().seriesCount).toBe(1))
    })

    it('labels the most recent billing period marker that falls inside the range', async () => {
        render(
            <BillingLineGraph
                series={SERIES}
                dates={DATES}
                hiddenSeries={[]}
                billingPeriodMarkers={[{ date: dayjs.utc('2026-01-02') }]}
            />
        )

        expect(await screen.findByText('New billing period')).toBeTruthy()
    })

    it('draws no marker when the billing period start is outside the plotted range', async () => {
        render(
            <BillingLineGraph
                series={SERIES}
                dates={DATES}
                hiddenSeries={[]}
                billingPeriodMarkers={[{ date: dayjs.utc('2025-12-01') }]}
            />
        )

        await waitFor(() => expect(getHogChart().seriesCount).toBe(2))
        expect(screen.queryByText('New billing period')).toBeNull()
    })
})

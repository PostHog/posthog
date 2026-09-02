import { cleanup, render, screen, waitFor } from '@testing-library/react'

import {
    createDefaultTooltipAccessor,
    ensureJsdom,
    getHogChart,
    hoverUntilTooltip,
} from '@posthog/quill-charts/testing'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { BillingLineGraph, type BillingSeriesType } from './BillingLineGraph'

// jsdom has no CSS custom properties, so the real `getSeriesColor` resolves every index to the
// same fallback color — masking a regression where colouring switches from series id to position.
// Mock only that function (keeping the rest of the module, e.g. the theme's graph colors) to
// distinct, valid CSS colors so the two are distinguishable in this test.
jest.mock('lib/colors', () => ({
    ...jest.requireActual('lib/colors'),
    getSeriesColor: (index: number) => ['#ff0000', '#0000ff'][index],
}))

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

    it('colors the surviving series by its id, not its position after filtering', async () => {
        render(<BillingLineGraph series={SERIES} dates={DATES} hiddenSeries={[0]} />)

        const chart = getHogChart()
        await waitFor(() => expect(chart.seriesCount).toBe(1))

        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 0, DATES.length))
        await waitFor(() => expect(tooltip.rows()).toEqual(['Recordings']))
        // If colouring switched to positional index, the survivor would wrongly pick up series 0's color
        // (mocked '#ff0000') instead of its own id's color (mocked '#0000ff').
        expect(tooltip.swatchColors()).toEqual(['rgb(0, 0, 255)'])
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

    it('draws a dashed line per in-range marker but labels only the most recent one', async () => {
        const { container } = render(
            <BillingLineGraph
                series={SERIES}
                dates={DATES}
                hiddenSeries={[]}
                billingPeriodMarkers={[
                    { date: dayjs.utc('2025-12-01') }, // out of range — no line, no label
                    { date: dayjs.utc('2026-01-01') },
                    { date: dayjs.utc('2026-01-02') }, // most recent in-range marker
                ]}
            />
        )

        await screen.findByText('New billing period')

        const lines = container.querySelectorAll('[data-attr="billing-period-marker-line"]')
        expect(lines).toHaveLength(2)

        const labels = container.querySelectorAll('[data-attr="billing-period-marker-label"]')
        expect(labels).toHaveLength(1)

        const lineLefts = Array.from(lines).map((line) => (line as HTMLElement).style.left)
        const labelLeft = (labels[0] as HTMLElement).style.left
        // The label anchors to the later of the two in-range markers, not just the last line drawn.
        expect(labelLeft).toBe(lineLefts[1])
    })

    it('snaps a mid-day marker timestamp to midnight UTC rather than drifting toward the next label', async () => {
        const lineLeftFor = async (date: ReturnType<typeof dayjs.utc>): Promise<string> => {
            const { container, unmount } = render(
                <BillingLineGraph series={SERIES} dates={DATES} hiddenSeries={[]} billingPeriodMarkers={[{ date }]} />
            )
            await screen.findByText('New billing period')
            const line = container.querySelector<HTMLElement>('[data-attr="billing-period-marker-line"]')
            const left = line!.style.left
            unmount()
            return left
        }

        // Without startOf('day') the mid-day timestamp would resolve partway between the Jan 2
        // and Jan 3 labels instead of landing exactly on Jan 2's x, same as an exact-midnight marker.
        const midnightLeft = await lineLeftFor(dayjs.utc('2026-01-02'))
        const midDayLeft = await lineLeftFor(dayjs.utc('2026-01-02T14:30:00Z'))
        expect(midDayLeft).toBe(midnightLeft)
    })

    it('applies valueFormatter to both the y-axis ticks and the tooltip values', async () => {
        render(
            <BillingLineGraph
                series={SERIES}
                dates={DATES}
                hiddenSeries={[]}
                valueFormatter={(value) => `$${value.toLocaleString()}`}
            />
        )

        const chart = getHogChart()
        await waitFor(() => expect(chart.yTicks().length).toBeGreaterThan(0))
        expect(chart.yTicks().every((tick) => tick.startsWith('$'))).toBe(true)

        const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 0, DATES.length))
        await waitFor(() => expect(tooltip.value('Events')).toBe('$10'))
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

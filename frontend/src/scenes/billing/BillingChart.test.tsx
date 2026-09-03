import { cleanup, render, screen, waitFor } from '@testing-library/react'

import {
    createDefaultTooltipAccessor,
    ensureJsdom,
    getHogChart,
    hoverUntilTooltip,
} from '@posthog/quill-charts/testing'

import { dayjs } from 'lib/dayjs'

import { initKeaTests } from '~/test/init'

import { BillingChart, type BillingSeriesType, runningTotal } from './BillingChart'

// jsdom has no CSS custom properties, so the real `getSeriesColor` resolves every index to the
// same fallback color, which would mask a regression where colouring switches from series id to
// position. Mock only that function (keeping the rest of the module, e.g. the theme's graph
// colors) to distinct, valid CSS colors so the two are distinguishable in this test.
jest.mock('lib/colors', () => ({
    ...jest.requireActual('lib/colors'),
    getSeriesColor: (index: number) => ['#ff0000', '#0000ff'][index],
}))

const DATES = ['2026-01-01', '2026-01-02', '2026-01-03']

const SERIES: BillingSeriesType[] = [
    { id: 0, label: 'Events', data: [10, 20, 30], dates: DATES },
    { id: 1, label: 'Recordings', data: [1, 2, 3], dates: DATES },
]

describe('BillingChart', () => {
    beforeEach(() => {
        ensureJsdom()
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders only the series that are not hidden', async () => {
        render(<BillingChart series={SERIES} dates={DATES} hiddenSeries={[1]} />)

        await waitFor(() => expect(getHogChart().seriesCount).toBe(1))
    })

    it('colors the surviving series by its id, not its position after filtering', async () => {
        render(<BillingChart series={SERIES} dates={DATES} hiddenSeries={[0]} />)

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
            <BillingChart
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
            <BillingChart
                series={SERIES}
                dates={DATES}
                hiddenSeries={[]}
                billingPeriodMarkers={[
                    { date: dayjs.utc('2025-12-01') }, // out of range: no line, no label
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
                <BillingChart series={SERIES} dates={DATES} hiddenSeries={[]} billingPeriodMarkers={[{ date }]} />
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
            <BillingChart
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
            <BillingChart
                series={SERIES}
                dates={DATES}
                hiddenSeries={[]}
                billingPeriodMarkers={[{ date: dayjs.utc('2025-12-01') }]}
            />
        )

        await waitFor(() => expect(getHogChart().seriesCount).toBe(2))
        expect(screen.queryByText('New billing period')).toBeNull()
    })

    describe('the series cap', () => {
        // Enough distinct totals to tell the largest from the rest, ranked by their sum over the range.
        const MANY: BillingSeriesType[] = [0, 1, 2, 3].map((id) => ({
            id,
            label: `Project ${id}`,
            data: [id, id],
            dates: DATES,
        }))

        it('draws no more than the cap and says how many it left out', async () => {
            render(<BillingChart series={MANY} dates={DATES} hiddenSeries={[]} maxSeries={2} />)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(2))
            expect(await screen.findByText(/2 more are in the table below/)).toBeTruthy()
        })

        it('keeps the largest series when it caps', async () => {
            render(<BillingChart series={MANY} dates={DATES} hiddenSeries={[]} maxSeries={2} />)

            const chart = getHogChart()
            await waitFor(() => expect(chart.seriesCount).toBe(2))

            const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, 0, DATES.length))
            await waitFor(() => expect(new Set(tooltip.rows())).toEqual(new Set(['Project 3', 'Project 2'])))
        })

        it('says nothing when every series fits', async () => {
            render(<BillingChart series={MANY} dates={DATES} hiddenSeries={[]} maxSeries={10} />)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(4))
            expect(screen.queryByText(/more are in the table below/)).toBeNull()
        })

        it('does not let hidden series take up room under the cap', async () => {
            // Two of four are hidden, so the two that remain fit and nothing is left out.
            render(<BillingChart series={MANY} dates={DATES} hiddenSeries={[2, 3]} maxSeries={2} />)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(2))
            expect(screen.queryByText(/more are in the table below/)).toBeNull()
        })
    })

    describe('the chart type', () => {
        const drawn = (container: HTMLElement): string | null =>
            container.querySelector('[data-attr="billing-chart-bar"]')
                ? 'bar'
                : container.querySelector('[data-attr="billing-chart-line"]')
                  ? 'line'
                  : null

        it('draws lines by default', async () => {
            const { container } = render(<BillingChart series={SERIES} dates={DATES} hiddenSeries={[]} />)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(2))
            expect(drawn(container)).toBe('line')
        })

        it('draws stacked bars when asked', async () => {
            const { container } = render(
                <BillingChart series={SERIES} dates={DATES} hiddenSeries={[]} chartType="bar" />
            )

            await waitFor(() => expect(getHogChart().seriesCount).toBe(2))
            expect(drawn(container)).toBe('bar')
        })

        it('caps and hides series the same way whichever type is drawn', async () => {
            // The series preparation is shared, so the cap and the hidden-series filter must not
            // depend on which chart consumes the result.
            const many: BillingSeriesType[] = [0, 1, 2, 3].map((id) => ({
                id,
                label: `Project ${id}`,
                data: [id, id],
                dates: DATES,
            }))

            render(<BillingChart series={many} dates={DATES} hiddenSeries={[0]} maxSeries={2} chartType="bar" />)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(2))
            expect(await screen.findByText(/1 more are in the table below/)).toBeTruthy()
        })
    })

    describe('the cumulative line', () => {
        const LABEL = 'Cumulative spend'
        // The middle label: the last one sits on the plot's right edge, which the right-hand axis
        // occupies, so a hover there lands in the gutter rather than on the chart.
        const middle = 1

        it('draws the running total of the visible series against a right-hand axis', async () => {
            render(
                <BillingChart series={SERIES} dates={DATES} hiddenSeries={[]} chartType="bar" cumulativeLabel={LABEL} />
            )

            const chart = getHogChart()
            await waitFor(() => expect(chart.seriesCount).toBe(3))
            expect(chart.hasRightAxis).toBe(true)

            // (10 + 1) + (20 + 2)
            const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, middle, DATES.length))
            await waitFor(() => expect(tooltip.value(LABEL)).toBe('33'))
        })

        it('leaves hidden series out of the running total', async () => {
            render(
                <BillingChart
                    series={SERIES}
                    dates={DATES}
                    hiddenSeries={[1]}
                    chartType="bar"
                    cumulativeLabel={LABEL}
                />
            )

            const chart = getHogChart()
            await waitFor(() => expect(chart.seriesCount).toBe(2))

            // 10 + 20, with Recordings hidden.
            const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, middle, DATES.length))
            await waitFor(() => expect(tooltip.value(LABEL)).toBe('30'))
        })

        it('counts the series the cap leaves undrawn', async () => {
            const many: BillingSeriesType[] = [0, 1, 2, 3].map((id) => ({
                id,
                label: `Project ${id}`,
                data: [id, id, id],
                dates: DATES,
            }))

            render(
                <BillingChart
                    series={many}
                    dates={DATES}
                    hiddenSeries={[]}
                    maxSeries={2}
                    chartType="bar"
                    cumulativeLabel={LABEL}
                />
            )

            const chart = getHogChart()
            // The two largest plus the line. The two the cap dropped are not drawn, but they are
            // still spend, so they still count.
            await waitFor(() => expect(chart.seriesCount).toBe(3))
            expect(await screen.findByText(/Charting the 2 largest series. 2 more are in the table below/)).toBeTruthy()

            // (0 + 1 + 2 + 3) per period, over two periods.
            const tooltip = createDefaultTooltipAccessor(await hoverUntilTooltip(chart.element, middle, DATES.length))
            await waitFor(() => expect(tooltip.value(LABEL)).toBe('12'))
        })

        it('is drawn over lines too, and named under the chart since there is no legend', async () => {
            render(<BillingChart series={SERIES} dates={DATES} hiddenSeries={[]} cumulativeLabel={LABEL} />)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(3))
            expect(await screen.findByText(/Dashed line: cumulative spend/)).toBeTruthy()
        })

        it('is not drawn unless asked for', async () => {
            render(<BillingChart series={SERIES} dates={DATES} hiddenSeries={[]} chartType="bar" />)

            const chart = getHogChart()
            await waitFor(() => expect(chart.seriesCount).toBe(2))
            expect(chart.hasRightAxis).toBe(false)
            expect(screen.queryByText(/Dashed line/)).toBeNull()
        })
    })
})

describe('runningTotal', () => {
    it('sums each period across the series, then carries the sum forward', () => {
        expect(runningTotal(SERIES, DATES.length)).toEqual([11, 33, 66])
    })

    it('treats a series shorter than the range as zero where it has no value', () => {
        expect(runningTotal([{ id: 0, label: 'Short', data: [5], dates: DATES }], DATES.length)).toEqual([5, 5, 5])
    })

    it('is zero throughout with nothing visible', () => {
        expect(runningTotal([], 3)).toEqual([0, 0, 0])
    })
})

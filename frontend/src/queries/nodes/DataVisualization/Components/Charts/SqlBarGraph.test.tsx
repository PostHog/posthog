import '@testing-library/jest-dom'

import { cleanup, configure, fireEvent, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { ChartSettings } from '~/queries/schema/schema-general'
import {
    type DataVizFixture,
    buildDataVisualizationQuery,
    getHogChart,
    renderDataVisualization,
    sqlChart,
} from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

// Neither timeout is set globally (jest.setup leaves asyncUtilTimeout at 1s, jest.config has no
// testTimeout → 5s): this heavy ~7-logic mount needs findByRole headroom beyond 1s on CI, and
// sqlChart.hoverTooltip's internal waits (findByRole + tooltip poll) can sum past the 5s default.
configure({ asyncUtilTimeout: 5000 })
jest.setTimeout(15000)

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

const MONTHS = ['2025-10-01', '2025-11-01', '2025-12-01', '2026-01-01', '2026-02-01', '2026-03-01']
const HOVER = 2

function barFixture(columns: { name: string; valueAt: (i: number) => unknown }[]): DataVizFixture {
    return {
        columns: ['month', ...columns.map((c) => c.name)],
        types: [['month', 'Date'], ...columns.map((c): [string, string] => [c.name, 'UInt64'])],
        results: MONTHS.map((m, i) => [m, ...columns.map((c) => c.valueAt(i))]),
    }
}

const twoSeries = (): DataVizFixture =>
    barFixture([
        { name: 'a', valueAt: (i) => (i + 1) * 100 },
        { name: 'b', valueAt: (i) => (i + 1) * 10 },
    ])

const renderBar = (
    display: ChartDisplayType,
    chartSettings: ChartSettings,
    fixture: DataVizFixture
): ReturnType<typeof renderDataVisualization> =>
    renderDataVisualization({
        query: buildDataVisualizationQuery({
            display,
            chartSettings: { xAxis: { column: 'month' }, ...chartSettings },
        }),
        response: fixture,
    })

describe('SqlBarGraph', () => {
    describe('bar layouts', () => {
        it.each([
            { name: 'grouped', display: ChartDisplayType.ActionsBar, extra: {} },
            { name: 'stacked', display: ChartDisplayType.ActionsStackedBar, extra: {} },
            {
                name: 'percent (100% stacked)',
                display: ChartDisplayType.ActionsStackedBar,
                extra: { stackBars100: true },
            },
        ])('renders both series in the $name layout', async ({ display, extra }) => {
            renderBar(display, { yAxis: [{ column: 'a' }, { column: 'b' }], ...extra }, twoSeries())

            await screen.findByRole('img', { name: /chart with 2 data series/i })
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
        })

        it('renders percentage y-axis ticks for the 100%-stacked layout', async () => {
            renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], stackBars100: true },
                twoSeries()
            )

            await screen.findByRole('img', { name: /chart with 2 data series/i })
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            for (const tick of getHogChart().yTicks()) {
                expect(tick).toMatch(/%$/)
            }
        })
    })

    describe('tooltip', () => {
        // Grouped/stacked bars split the band, so a band-center hover only deterministically lands on
        // a single bar — assert tooltip content with one series, layout/legend with two.
        it('shows the value, swatch, and x-label for a single series', async () => {
            renderBar(
                ChartDisplayType.ActionsBar,
                { yAxis: [{ column: 'a' }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 1000 }])
            )

            await screen.findByRole('img', { name: /chart with/i })
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            expect(tooltip.row('a')).toBe('3,000')
            expect(tooltip.title()).toBe('2025-12-01')
            expect(tooltip.swatchColors()).toHaveLength(1)
        })

        // Documented gap: unlike SqlLineGraph, SqlBarGraph passes no custom tooltip, so quill's
        // DefaultTooltip formats with toLocaleString and ignores per-column prefix/suffix/style.
        // When the bar chart gains a column-aware tooltip, this should become '$3,000'.
        it('does not yet apply per-column formatting to bar tooltip values', async () => {
            renderBar(
                ChartDisplayType.ActionsBar,
                { yAxis: [{ column: 'a', settings: { formatting: { prefix: '$', style: 'number' } } }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 1000 }])
            )

            await screen.findByRole('img', { name: /chart with/i })
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            expect(tooltip.row('a')).toBe('3,000')
        })
    })

    describe('legend', () => {
        const getLegend = (container: HTMLElement): HTMLElement =>
            container.querySelector<HTMLElement>('[data-attr="hog-chart-timeseries-bar-legend"]')!

        it('renders an in-chart legend listing every series when showLegend is set', async () => {
            const { container } = renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], showLegend: true },
                twoSeries()
            )

            await screen.findByRole('img', { name: /chart with 2 data series/i })
            const labels = [...getLegend(container).querySelectorAll('button')].map((b) => b.textContent)
            expect(labels).toEqual(['a', 'b'])
        })

        it('hides a series when its legend item is toggled off', async () => {
            const { container } = renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], showLegend: true },
                twoSeries()
            )

            await screen.findByRole('img', { name: /chart with 2 data series/i })
            const bButton = [...getLegend(container).querySelectorAll('button')].find((b) =>
                b.textContent?.includes('b')
            )!
            fireEvent.click(bButton)

            await waitFor(() => expect(getHogChart().seriesCount).toBe(1))
        })
    })

    describe('goal lines', () => {
        it('renders a goal line as a horizontal reference line', async () => {
            renderBar(
                ChartDisplayType.ActionsBar,
                { yAxis: [{ column: 'a' }], goalLines: [{ label: 'Target', value: 250, displayIfCrossed: true }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByRole('img', { name: /chart with/i })
            const lines = getHogChart().referenceLines()
            expect(lines.map((l) => l.label)).toEqual(['Target'])
            expect(lines[0].orientation).toBe('horizontal')
        })
    })

    describe('fallback to legacy', () => {
        // The quill bar chart has no trend-line support, so a bar series opting into a trend line
        // routes to the legacy chart.js path (no quill "chart with N data series" canvas).
        it('falls back to the legacy chart when a bar series requests a trend line', async () => {
            renderBar(
                ChartDisplayType.ActionsBar,
                { yAxis: [{ column: 'a', settings: { display: { trendLine: true } } }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            await waitFor(() => expect(document.querySelector('canvas')).toBeInTheDocument())
            expect(screen.queryByRole('img', { name: /chart with/i })).not.toBeInTheDocument()
        })
    })
})

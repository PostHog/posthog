import '@testing-library/jest-dom'

import { cleanup, configure, fireEvent, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { ChartSettings } from '~/queries/schema/schema-general'
import {
    type DataVizFixture,
    buildDataVisualizationQuery,
    getHogChart,
    HOVER,
    MONTHS,
    renderDataVisualization,
    sqlChart,
} from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

// Neither timeout is set globally (jest.setup leaves asyncUtilTimeout at 1s, jest.config has no
// testTimeout → 5s): this heavy ~7-logic mount needs findBy* headroom beyond 1s on CI, and
// sqlChart.hoverTooltip's internal waits (findBy* + tooltip poll) can sum past the 5s default.
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

            await screen.findByLabelText(/chart with 2 data series/i)
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
        })

        it('renders percentage y-axis ticks for the 100%-stacked layout', async () => {
            renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], stackBars100: true },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            await waitFor(() => expect(getHogChart().yTicks().length).toBeGreaterThan(0))
            for (const tick of getHogChart().yTicks()) {
                expect(tick).toMatch(/%$/)
            }
        })
    })

    describe('dual y-axis', () => {
        it.each([
            { name: 'grouped', display: ChartDisplayType.ActionsBar },
            { name: 'stacked', display: ChartDisplayType.ActionsStackedBar },
        ])('renders a right gutter formatted from its own column in the $name layout', async ({ display }) => {
            renderBar(
                display,
                {
                    yAxis: [
                        { column: 'a', settings: { formatting: { prefix: '$' } } },
                        {
                            column: 'b',
                            settings: { formatting: { suffix: '%' }, display: { yAxisPosition: 'right' } },
                        },
                    ],
                },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
            await waitFor(() => expect(getHogChart().hasRightAxis).toBe(true))
            const chart = getHogChart()
            expect(chart.yTicks().length).toBeGreaterThan(0)
            expect(chart.yTicks().every((tick) => tick.startsWith('$'))).toBe(true)
            const rightTicks = chart.yRightTicks()
            expect(rightTicks.length).toBeGreaterThan(0)
            expect(rightTicks.every((tick) => tick.endsWith('%'))).toBe(true)
        })

        it('renders the axis on the right when the only series targets the right axis', async () => {
            renderBar(
                ChartDisplayType.ActionsBar,
                { yAxis: [{ column: 'a', settings: { display: { yAxisPosition: 'right' } } }] },
                barFixture([{ name: 'a', valueAt: (i) => (i + 1) * 100 }])
            )

            await screen.findByLabelText(/chart with/i)
            await waitFor(() => expect(getHogChart().yRightTicks().length).toBeGreaterThan(0))
            expect(getHogChart().yTicks()).toHaveLength(0)
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

            await screen.findByLabelText(/chart with/i)
            const tooltip = await sqlChart.hoverTooltip(HOVER, MONTHS.length)

            // formatSqlSeriesValue output — matches the line/combo tooltips, not toLocaleString.
            expect(tooltip.value('a')).toBe('3000')
            expect(tooltip.label()).toBe('Dec 1, 2025')
            expect(tooltip.swatchColors()).toHaveLength(1)
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

            await screen.findByLabelText(/chart with 2 data series/i)
            const labels = [...getLegend(container).querySelectorAll('button')].map((b) => b.textContent)
            expect(labels).toEqual(['a', 'b'])
        })

        it('hides a series when its legend item is toggled off', async () => {
            const { container } = renderBar(
                ChartDisplayType.ActionsStackedBar,
                { yAxis: [{ column: 'a' }, { column: 'b' }], showLegend: true },
                twoSeries()
            )

            await screen.findByLabelText(/chart with 2 data series/i)
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

            await screen.findByLabelText(/chart with/i)
            const lines = getHogChart().referenceLines()
            expect(lines.map((l) => l.label)).toEqual(['Target'])
            expect(lines[0].orientation).toBe('horizontal')
        })
    })
})

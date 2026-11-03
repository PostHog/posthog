import { waitFor } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderChart, waitForChartTooltip } from '../../testing'
import { BoxPlot, type BoxPlotClickData, type BoxPlotConfig } from './BoxPlot'
import type { BoxPlotDatum, BoxPlotSeries } from './types'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const LABELS = ['Mon', 'Tue', 'Wed']

function datum(overrides: Partial<BoxPlotDatum> = {}): BoxPlotDatum {
    return { min: 0, p25: 25, median: 50, mean: 55, p75: 75, max: 100, ...overrides }
}

const TWO_SERIES: BoxPlotSeries[] = [
    {
        key: 'a',
        label: 'A',
        data: [datum({ median: 40 }), datum({ median: 50 }), datum({ median: 60 })],
    },
    {
        key: 'b',
        label: 'B',
        data: [datum({ median: 30 }), datum({ median: 45 }), datum({ median: 55 })],
    },
]

describe('BoxPlot', () => {
    it('renders the canvas and reports series count via aria-label', () => {
        const { chart } = renderChart(<BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
    })

    it('renders a legend when requested', () => {
        const { container } = renderChart(
            <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} config={{ legend: { show: true } }} />
        )
        const buttons = container.querySelectorAll('[data-attr="hog-chart-box-plot-legend"] button')
        expect(Array.from(buttons, (button) => button.textContent)).toEqual(['A', 'B'])
    })

    it('renders y-axis ticks for the value range that spans whiskers', () => {
        const series: BoxPlotSeries[] = [
            {
                key: 'a',
                label: 'A',
                data: [datum({ min: 0, max: 200 }), datum({ min: 10, max: 220 })],
            },
        ]
        const { chart } = renderChart(<BoxPlot series={series} labels={['Mon', 'Tue']} theme={THEME} />)
        const ticks = chart.yTicks()
        expect(ticks.length).toBeGreaterThan(0)
        const nums = ticks.map((t) => parseFloat(t.replace(/[^\d.-]/g, '')))
        const maxTick = Math.max(...nums.filter((n) => Number.isFinite(n)))
        // The y-domain must span the largest whisker max (220), not just the median values.
        expect(maxTick).toBeGreaterThanOrEqual(200)
    })

    it('ends the y-axis at the whisker, not at a clipped outlier max', () => {
        const series: BoxPlotSeries[] = [
            {
                key: 'a',
                label: 'A',
                data: [
                    datum({ min: 0, max: 1_000_000, whiskerMax: 120 }),
                    datum({ min: 10, max: 900_000, whiskerMax: 130 }),
                ],
            },
        ]
        const { chart } = renderChart(<BoxPlot series={series} labels={['Mon', 'Tue']} theme={THEME} />)
        const nums = chart.yTicks().map((t) => parseFloat(t.replace(/[^\d.-]/g, '')))
        const maxTick = Math.max(...nums.filter((n) => Number.isFinite(n)))
        expect(maxTick).toBeGreaterThanOrEqual(130)
        expect(maxTick).toBeLessThan(1000)
    })

    it.each([
        { name: 'above the upper whisker', override: { mean: 700, whiskerMax: 100 }, expectTick: 700 },
        { name: 'below the lower whisker', override: { mean: -50, whiskerMin: 10 }, expectTick: -50 },
    ])('keeps a mean $name inside the y-axis', ({ override, expectTick }) => {
        const series: BoxPlotSeries[] = [{ key: 'a', label: 'A', data: [datum(override)] }]
        const { chart } = renderChart(<BoxPlot series={series} labels={['Mon']} theme={THEME} />)
        const nums = chart
            .yTicks()
            .map((t) => parseFloat(t.replace(/[^\d.-]/g, '')))
            .filter((n) => Number.isFinite(n))
        expect(Math.max(...nums)).toBeGreaterThanOrEqual(Math.max(expectTick, 0))
        expect(Math.min(...nums)).toBeLessThanOrEqual(Math.min(expectTick, 0))
    })

    it('allocates left margin wide enough for the whisker-derived y ticks (not just medians)', () => {
        // Regression: clipping of the y-tick column. `useChartMargins` reads
        // `seriesValueRange(adaptedSeries)` to size the left margin, so the adapted series'
        // `data` must include the whisker extremes (not just medians) — `valueRangeSeries`
        // alone only reaches the d3 y-domain. Tick set covers the whisker range here, with
        // visual margin sizing left to Storybook snapshots (jsdom stubs `measureText`).
        const series: BoxPlotSeries[] = [
            {
                key: 'a',
                label: 'A',
                data: [
                    datum({ min: 0, p25: 25, median: 30, mean: 35, p75: 50, max: 280 }),
                    datum({ min: 0, p25: 28, median: 35, mean: 40, p75: 55, max: 270 }),
                ],
            },
        ]
        const { chart } = renderChart(<BoxPlot series={series} labels={['Mon', 'Tue']} theme={THEME} />)
        const ticks = chart.yTicks()
        const maxTickNumeric = Math.max(
            ...ticks.map((t) => parseFloat(t.replace(/[^\d.-]/g, ''))).filter((n) => Number.isFinite(n))
        )
        expect(maxTickNumeric).toBeGreaterThanOrEqual(250)
    })

    it('lists the labels down the y-axis and the values along x when horizontal', () => {
        const { chart } = renderChart(
            <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} config={{ axisOrientation: 'horizontal' }} />
        )
        expect(chart.yTicks()).toEqual(LABELS)
        const values = chart.xTicks().map((tick) => parseFloat(tick.replace(/[^\d.-]/g, '')))
        expect(Math.max(...values)).toBeGreaterThanOrEqual(100)
    })

    it('forwards `dataAttr` to the chart wrapper', () => {
        const { chart } = renderChart(
            <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} dataAttr="boxplot-instance" />
        )
        expect(chart.element.getAttribute('data-attr')).toBe('boxplot-instance')
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderChart(<BoxPlot series={[]} labels={[]} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('tolerates null entries in series data', () => {
        const series: BoxPlotSeries[] = [{ key: 'a', label: 'A', data: [datum(), null, datum()] }]
        const { chart } = renderChart(<BoxPlot series={series} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(1)
    })

    it('skips excluded series in seriesCount', () => {
        const series: BoxPlotSeries[] = [
            { key: 'a', label: 'A', data: [datum(), datum(), datum()] },
            {
                key: 'b',
                label: 'B',
                data: [datum(), datum(), datum()],
                visibility: { excluded: true },
            },
        ]
        const { chart } = renderChart(<BoxPlot series={series} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(1)
    })

    describe('tooltip context', () => {
        it('exposes the original BoxPlotDatum on each series via meta.datums (six stats reachable)', async () => {
            const { chart } = renderChart(<BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            const aMeta = tooltip.series.a!.series.meta as { datums: (BoxPlotDatum | null)[] }
            expect(aMeta.datums[1]).toEqual(
                expect.objectContaining({
                    min: expect.any(Number),
                    p25: expect.any(Number),
                    median: 50,
                    mean: expect.any(Number),
                    p75: expect.any(Number),
                    max: expect.any(Number),
                })
            )
        })

        it('includes the x-axis label in the tooltip context', async () => {
            const { chart } = renderChart(<BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.label).toBe('Tue')
        })
    })

    describe('tooltip rendering', () => {
        const SINGLE_SERIES: BoxPlotSeries[] = [
            {
                key: 'a',
                label: 'A-label',
                data: [datum({ min: 1, p25: 2, median: 3, mean: 4, p75: 5, max: 6 }), datum(), datum()],
            },
        ]

        it('renders the six stats in the canonical order (Max → p75 → Median → Mean → p25 → Min)', async () => {
            const { chart } = renderChart(<BoxPlot series={SINGLE_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(0)
            const tooltipEl = await waitForChartTooltip()
            const rowLabels = Array.from(tooltipEl.querySelectorAll('tr')).map((tr) =>
                (tr.firstElementChild as HTMLElement).textContent!.trim()
            )
            expect(rowLabels).toEqual(['Max', '75th percentile', 'Median', 'Mean', '25th percentile', 'Min'])
        })

        it.each([
            {
                name: 'lists the clipped whiskers between the true extremes and the box',
                override: { min: 1, p25: 20, median: 30, mean: 40, p75: 50, max: 900, whiskerMin: 10, whiskerMax: 80 },
                rows: [
                    ['Max', '900'],
                    ['Upper whisker', '80'],
                    ['75th percentile', '50'],
                    ['Median', '30'],
                    ['Mean', '40'],
                    ['25th percentile', '20'],
                    ['Lower whisker', '10'],
                    ['Min', '1'],
                ],
            },
            {
                name: 'lists only the whisker that is clipped',
                override: { min: 1, p25: 20, median: 30, mean: 40, p75: 50, max: 900, whiskerMin: 1, whiskerMax: 80 },
                rows: [
                    ['Max', '900'],
                    ['Upper whisker', '80'],
                    ['75th percentile', '50'],
                    ['Median', '30'],
                    ['Mean', '40'],
                    ['25th percentile', '20'],
                    ['Min', '1'],
                ],
            },
            {
                name: 'omits whisker rows that equal the true extremes',
                override: { min: 1, p25: 20, median: 30, mean: 40, p75: 50, max: 90, whiskerMin: 1, whiskerMax: 90 },
                rows: [
                    ['Max', '90'],
                    ['75th percentile', '50'],
                    ['Median', '30'],
                    ['Mean', '40'],
                    ['25th percentile', '20'],
                    ['Min', '1'],
                ],
            },
            {
                name: 'formats every row with the tooltip value formatter',
                override: { min: 1, p25: 20, median: 30, mean: 40, p75: 50, max: 90, whiskerMax: 80 },
                config: { tooltip: { valueFormatter: (v: number) => `${v}ms` } },
                rows: [
                    ['Max', '90ms'],
                    ['Upper whisker', '80ms'],
                    ['75th percentile', '50ms'],
                    ['Median', '30ms'],
                    ['Mean', '40ms'],
                    ['25th percentile', '20ms'],
                    ['Min', '1ms'],
                ],
            },
        ])(
            '$name',
            async ({
                override,
                rows,
                config,
            }: {
                override: Partial<BoxPlotDatum>
                rows: string[][]
                config?: BoxPlotConfig
            }) => {
                const series: BoxPlotSeries[] = [
                    { key: 'a', label: 'A-label', data: [datum(override), datum(), datum()] },
                ]
                const { chart } = renderChart(<BoxPlot series={series} labels={LABELS} theme={THEME} config={config} />)
                chart.hoverAtIndex(0)
                const tooltipEl = await waitForChartTooltip()
                const rendered = Array.from(tooltipEl.querySelectorAll('tr')).map((tr) => [
                    (tr.firstElementChild as HTMLElement).textContent!.trim(),
                    (tr.lastElementChild as HTMLElement).textContent!.trim(),
                ])
                expect(rendered).toEqual(rows)
            }
        )

        it('renders the values in the canonical row order', async () => {
            const { chart } = renderChart(<BoxPlot series={SINGLE_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(0)
            const tooltipEl = await waitForChartTooltip()
            const values = Array.from(tooltipEl.querySelectorAll('tr')).map((tr) =>
                (tr.lastElementChild as HTMLElement).textContent!.trim()
            )
            expect(values).toEqual(['6', '5', '3', '4', '2', '1'])
        })

        it('shows the x label in the header', async () => {
            const { chart } = renderChart(<BoxPlot series={SINGLE_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(0)
            const tooltipEl = await waitForChartTooltip()
            expect(tooltipEl.textContent).toContain('Mon')
        })

        it('renders one stat table per visible series when grouped (multi-series)', async () => {
            const { chart } = renderChart(<BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(0)
            const tooltipEl = await waitForChartTooltip()
            // Per-series header labels show in grouped mode.
            expect(tooltipEl.textContent).toContain('A')
            expect(tooltipEl.textContent).toContain('B')
            expect(tooltipEl.querySelectorAll('table')).toHaveLength(2)
        })

        it('hides the per-series label when not grouped (single series)', async () => {
            const { chart } = renderChart(<BoxPlot series={SINGLE_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(0)
            const tooltipEl = await waitForChartTooltip()
            const headers = Array.from(tooltipEl.querySelectorAll('.font-semibold')).map((el) => el.textContent)
            // The single "Mon" header is the only font-semibold heading in single-series mode.
            expect(headers).toContain('Mon')
            expect(headers).not.toContain('A-label')
        })

        it('passes through to a user-supplied tooltip when provided', async () => {
            const userTooltip = jest.fn(
                (): React.ReactElement => <div data-attr="custom-boxplot-user-tooltip">custom</div>
            )
            const { chart } = renderChart(
                <BoxPlot series={SINGLE_SERIES} labels={LABELS} theme={THEME} tooltip={userTooltip} />
            )
            chart.hoverAtIndex(0)
            const tooltipEl = await waitForChartTooltip()
            expect(tooltipEl.querySelector('[data-attr="custom-boxplot-user-tooltip"]')).not.toBeNull()
            expect(userTooltip).toHaveBeenCalled()
        })
    })

    describe('click', () => {
        it('invokes onBoxClick with the clicked datum and cross-series data', async () => {
            const onBoxClick = jest.fn()
            const { chart } = renderChart(
                <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} onBoxClick={onBoxClick} />
            )
            await chart.clickAtIndex(1)
            await waitFor(() => expect(onBoxClick).toHaveBeenCalled())
            const arg = onBoxClick.mock.calls[0][0] as BoxPlotClickData
            expect(arg.dataIndex).toBe(1)
            expect(arg.label).toBe('Tue')
            // `series` is the primary (first visible) series — matches BarChart's onPointClick contract.
            expect(arg.series.key).toBe('a')
            expect(arg.datum.median).toBe(50)
            // crossSeriesData carries every visible series's datum at this column.
            expect(arg.crossSeriesData).toHaveLength(2)
            expect(arg.crossSeriesData.map((c) => c.series.key)).toEqual(['a', 'b'])
            expect(arg.crossSeriesData.map((c) => c.datum.median)).toEqual([50, 45])
        })
    })

    describe('error handling', () => {
        let consoleErrorSpy: jest.SpyInstance
        beforeEach(() => {
            consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
        })
        afterEach(() => {
            consoleErrorSpy.mockRestore()
        })

        it('reports render errors through onError', async () => {
            const onError = jest.fn()
            const tooltip = (): React.ReactNode => {
                throw new Error('boom')
            }
            const { chart } = renderChart(
                <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
            )
            chart.hoverAtIndex(1)
            await waitFor(() => expect(onError).toHaveBeenCalled())
        })
    })

    describe('children', () => {
        it('renders custom overlay children', () => {
            const { chart } = renderChart(
                <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME}>
                    <div data-attr="custom-box-child" />
                </BoxPlot>
            )
            expect(chart.element.querySelector('[data-attr="custom-box-child"]')).not.toBeNull()
        })
    })
})

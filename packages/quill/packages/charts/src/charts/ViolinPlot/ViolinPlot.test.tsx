import type { ChartTheme } from '../../core/types'
import { renderChart, waitForChartTooltip } from '../../testing'
import type { ViolinPlotDatum, ViolinPlotSeries } from './types'
import { ViolinPlot } from './ViolinPlot'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e', '#2ca02c'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const LABELS = ['Mon', 'Tue', 'Wed']

function datum(values: number[] = [10, 20, 30, 40, 50]): ViolinPlotDatum {
    return { values }
}

const TWO_SERIES: ViolinPlotSeries[] = [
    { key: 'a', label: 'A', data: [datum(), datum([5, 15, 25]), datum([30, 40, 50, 60])] },
    { key: 'b', label: 'B', data: [datum([12, 18]), datum([20, 22, 24]), datum([1, 100])] },
]

function rowTexts(tooltip: HTMLElement): string[][] {
    return Array.from(tooltip.querySelectorAll('tr')).map((row) =>
        Array.from(row.children, (cell) => cell.textContent!.trim())
    )
}

describe('ViolinPlot', () => {
    it('renders the canvas and reports series count via aria-label', () => {
        const { chart } = renderChart(<ViolinPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)

        expect(chart.seriesCount).toBe(2)
    })

    it('renders a legend when requested', () => {
        const { container } = renderChart(
            <ViolinPlot series={TWO_SERIES} labels={LABELS} theme={THEME} config={{ legend: { show: true } }} />
        )

        const buttons = container.querySelectorAll('[data-attr="hog-chart-violin-plot-legend"] button')
        expect(Array.from(buttons, (button) => button.textContent)).toEqual(['A', 'B'])
    })

    it('spans the y-axis over every observation, not only the medians', () => {
        const series: ViolinPlotSeries[] = [{ key: 'a', label: 'A', data: [datum([0, 5, 210]), datum([10, 220])] }]

        const { chart } = renderChart(<ViolinPlot series={series} labels={['Mon', 'Tue']} theme={THEME} />)

        const ticks = chart.yTicks().map((tick) => parseFloat(tick.replace(/[^\d.-]/g, '')))
        expect(Math.max(...ticks.filter(Number.isFinite))).toBeGreaterThanOrEqual(200)
    })

    it('forwards `dataAttr` to the chart wrapper', () => {
        const { container } = renderChart(
            <ViolinPlot series={TWO_SERIES} labels={LABELS} theme={THEME} dataAttr="my-violin" />
        )

        expect(container.querySelector('[data-attr="my-violin"]')).not.toBeNull()
    })

    it('renders an empty chart without crashing', () => {
        expect(() => renderChart(<ViolinPlot series={[]} labels={[]} theme={THEME} />)).not.toThrow()
    })

    it('tolerates null entries and groups without finite values', () => {
        const series: ViolinPlotSeries[] = [{ key: 'a', label: 'A', data: [datum(), null, datum([Number.NaN])] }]

        const { chart } = renderChart(<ViolinPlot series={series} labels={LABELS} theme={THEME} />)

        expect(chart.seriesCount).toBe(1)
    })

    it('skips excluded series in seriesCount', () => {
        const series: ViolinPlotSeries[] = [
            { key: 'a', label: 'A', data: [datum()] },
            { key: 'b', label: 'B', data: [datum()], visibility: { excluded: true } },
        ]

        const { chart } = renderChart(<ViolinPlot series={series} labels={['Mon']} theme={THEME} />)

        expect(chart.seriesCount).toBe(1)
    })

    describe('tooltip context', () => {
        it('includes the x-axis label and the original observations', async () => {
            const { chart } = renderChart(<ViolinPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)

            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()

            expect(tooltip.label).toBe('Tue')
            const meta = tooltip.series.a!.series.meta as { datums: (ViolinPlotDatum | null)[] }
            expect(meta.datums[1]).toEqual({ values: [5, 15, 25] })
        })
    })

    describe('tooltip rendering', () => {
        const SINGLE_SERIES: ViolinPlotSeries[] = [
            { key: 'a', label: 'A-label', data: [datum([1, 2, 3, 4, 5]), datum(), datum()] },
        ]

        it('lists the statistics in order from Count through Max to Min', async () => {
            const { chart } = renderChart(<ViolinPlot series={SINGLE_SERIES} labels={LABELS} theme={THEME} />)

            chart.hoverAtIndex(0)
            const tooltip = await waitForChartTooltip()

            expect(rowTexts(tooltip)).toEqual([
                ['Count', '5'],
                ['Max', '5'],
                ['75th percentile', '4'],
                ['Median', '3'],
                ['Mean', '3'],
                ['25th percentile', '2'],
                ['Min', '1'],
            ])
        })

        it('leaves values that are not positive out of the statistics on a log axis', async () => {
            const series: ViolinPlotSeries[] = [{ key: 'a', label: 'A', data: [datum([-1, 0, 10, 100, 1000])] }]
            const { chart } = renderChart(
                <ViolinPlot series={series} labels={['Mon']} theme={THEME} config={{ yScaleType: 'log' }} />
            )

            chart.hoverAtIndex(0)
            const tooltip = await waitForChartTooltip()

            expect(rowTexts(tooltip)).toEqual([
                ['Count', '3'],
                ['Max', '1,000'],
                ['75th percentile', '550'],
                ['Median', '100'],
                ['Mean', '370'],
                ['25th percentile', '55'],
                ['Min', '10'],
            ])
        })

        it('keeps values that are not positive in the statistics on a linear axis', async () => {
            const series: ViolinPlotSeries[] = [{ key: 'a', label: 'A', data: [datum([-1, 0, 10, 100, 1000])] }]
            const { chart } = renderChart(<ViolinPlot series={series} labels={['Mon']} theme={THEME} />)

            chart.hoverAtIndex(0)
            const tooltip = await waitForChartTooltip()

            expect(rowTexts(tooltip)[0]).toEqual(['Count', '5'])
            expect(rowTexts(tooltip)[3]).toEqual(['Median', '10'])
        })

        it('renders a consumer `tooltip` instead of the default one', async () => {
            const { chart } = renderChart(
                <ViolinPlot
                    series={SINGLE_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    tooltip={(ctx) => <div data-attr="custom-violin-tooltip">{ctx.label}</div>}
                />
            )

            chart.hoverAtIndex(0)
            const tooltip = await waitForChartTooltip()

            expect(tooltip.querySelector('[data-attr="custom-violin-tooltip"]')?.textContent).toBe('Mon')
            expect(tooltip.querySelector('table')).toBeNull()
        })

        it('formats the statistics, but not the count, with the tooltip value formatter', async () => {
            const { chart } = renderChart(
                <ViolinPlot
                    series={SINGLE_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ tooltip: { valueFormatter: (value: number) => `${value}ms` } }}
                />
            )

            chart.hoverAtIndex(0)
            const tooltip = await waitForChartTooltip()

            expect(rowTexts(tooltip)[0]).toEqual(['Count', '5'])
            expect(rowTexts(tooltip)[1]).toEqual(['Max', '5ms'])
        })

        it('shows the x label in the header and hides the series label for a single series', async () => {
            const { chart } = renderChart(<ViolinPlot series={SINGLE_SERIES} labels={LABELS} theme={THEME} />)

            chart.hoverAtIndex(0)
            const tooltip = await waitForChartTooltip()

            expect(tooltip.textContent).toContain('Mon')
            expect(tooltip.textContent).not.toContain('A-label')
        })

        it('renders one table per visible series when grouped', async () => {
            const { chart } = renderChart(<ViolinPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)

            chart.hoverAtIndex(0)
            const tooltip = await waitForChartTooltip()

            expect(tooltip.querySelectorAll('table')).toHaveLength(2)
            expect(tooltip.textContent).toContain('A')
            expect(tooltip.textContent).toContain('B')
        })
    })

    it('renders custom overlay children', () => {
        const { container } = renderChart(
            <ViolinPlot series={TWO_SERIES} labels={LABELS} theme={THEME}>
                <div data-attr="violin-overlay" />
            </ViolinPlot>
        )

        expect(container.querySelector('[data-attr="violin-overlay"]')).not.toBeNull()
    })
})

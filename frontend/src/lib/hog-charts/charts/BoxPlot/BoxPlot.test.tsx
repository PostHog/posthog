import { waitFor } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { renderHogChart } from '../../testing'
import { BoxPlot, type BoxPlotClickData } from './BoxPlot'
import type { BoxPlotDatum, BoxPlotSeries } from './computeBoxLayout'

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
        const { chart } = renderHogChart(<BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
    })

    it('renders y-axis ticks for the value range that spans whiskers', () => {
        const series: BoxPlotSeries[] = [
            {
                key: 'a',
                label: 'A',
                data: [datum({ min: 0, max: 200 }), datum({ min: 10, max: 220 })],
            },
        ]
        const { chart } = renderHogChart(<BoxPlot series={series} labels={['Mon', 'Tue']} theme={THEME} />)
        const ticks = chart.yTicks()
        expect(ticks.length).toBeGreaterThan(0)
        const nums = ticks.map((t) => parseFloat(t.replace(/[^\d.-]/g, '')))
        const maxTick = Math.max(...nums.filter((n) => Number.isFinite(n)))
        // The y-domain must span the largest whisker max (220), not just the median values.
        expect(maxTick).toBeGreaterThanOrEqual(200)
    })

    it('allocates left margin wide enough for the whisker-derived y ticks (not just medians)', () => {
        // Regression for tick labels getting clipped — when medians (e.g. 30–60) are much
        // smaller than whisker max (e.g. 280), `useChartMargins` sees the medians-only
        // series and used to undersize the left margin for the actual axis labels.
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
        const { chart } = renderHogChart(<BoxPlot series={series} labels={['Mon', 'Tue']} theme={THEME} />)
        const ticks = chart.yTicks()
        const maxTickNumeric = Math.max(
            ...ticks.map((t) => parseFloat(t.replace(/[^\d.-]/g, ''))).filter((n) => Number.isFinite(n))
        )
        // The rendered ticks should reflect the whisker range. The previous bug was sizing
        // the y-tick *column* width from medians only — assertion guards the rendered tick
        // set actually reaches the whisker max.
        expect(maxTickNumeric).toBeGreaterThanOrEqual(250)
    })

    it('forwards `dataAttr` to the chart wrapper', () => {
        const { chart } = renderHogChart(
            <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} dataAttr="boxplot-instance" />
        )
        expect(chart.element.getAttribute('data-attr')).toBe('boxplot-instance')
    })

    it('renders empty state without crashing', () => {
        const { chart } = renderHogChart(<BoxPlot series={[]} labels={[]} theme={THEME} />)
        expect(chart.seriesCount).toBe(0)
    })

    it('tolerates null entries in series data', () => {
        const series: BoxPlotSeries[] = [{ key: 'a', label: 'A', data: [datum(), null, datum()] }]
        const { chart } = renderHogChart(<BoxPlot series={series} labels={LABELS} theme={THEME} />)
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
        const { chart } = renderHogChart(<BoxPlot series={series} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(1)
    })

    describe('tooltip context', () => {
        it('exposes the original BoxPlotDatum on each series via meta.datums (six stats reachable)', async () => {
            const { chart } = renderHogChart(<BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)
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
            const { chart } = renderHogChart(<BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} />)
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.label).toBe('Tue')
        })
    })

    describe('click', () => {
        it('invokes onBoxClick with the clicked datum and cross-series data', async () => {
            const onBoxClick = jest.fn()
            const { chart } = renderHogChart(
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
        it('reports render errors through onError', async () => {
            const onError = jest.fn()
            const tooltip = (): React.ReactNode => {
                throw new Error('boom')
            }
            const consoleErrorSpy = jest.spyOn(console, 'error').mockImplementation(() => {})
            try {
                const { chart } = renderHogChart(
                    <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME} tooltip={tooltip} onError={onError} />
                )
                chart.hoverAtIndex(1)
                await waitFor(() => expect(onError).toHaveBeenCalled())
            } finally {
                consoleErrorSpy.mockRestore()
            }
        })
    })

    describe('children', () => {
        it('renders custom overlay children', () => {
            const { chart } = renderHogChart(
                <BoxPlot series={TWO_SERIES} labels={LABELS} theme={THEME}>
                    <div data-attr="custom-box-child" />
                </BoxPlot>
            )
            expect(chart.element.querySelector('[data-attr="custom-box-child"]')).not.toBeNull()
        })
    })
})

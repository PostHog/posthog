import { fireEvent } from '@testing-library/react'

import { useChartLayout } from '../../core/chart-context'
import type { ChartTheme, Series } from '../../core/types'
import { getHogChart, renderHogChart } from '../../testing'
import { TimeSeriesBarChart } from './TimeSeriesBarChart'

const THEME: ChartTheme = {
    colors: ['#111', '#222', '#333'],
    backgroundColor: '#ffffff',
}
const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3] }]
const MULTI_SERIES: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3] },
    { key: 'b', label: 'B', data: [3, 2, 1] },
]

describe('TimeSeriesBarChart', () => {
    describe('config.xAxis', () => {
        it('hides x-axis ticks when xAxis.hide is true', () => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={THEME} config={{ xAxis: { hide: true } }} />
            )
            expect(chart.xTicks()).toHaveLength(0)
        })

        it('forwards an explicit xAxis.tickFormatter to the chart', () => {
            const explicit = (_v: string, i: number): string => `tick-${i}`
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={['14:00', '15:00', '16:00']}
                    theme={THEME}
                    config={{ xAxis: { tickFormatter: explicit } }}
                />
            )
            expect(chart.xTicks()).toEqual(['tick-0', 'tick-1', 'tick-2'])
        })

        it('builds an auto date formatter from xAxis.timezone + xAxis.interval', () => {
            const labels = ['2024-06-10', '2024-06-11', '2024-06-12']
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={labels}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC', interval: 'day' } }}
                />
            )
            const ticks = chart.xTicks()
            expect(ticks.length).toBeGreaterThan(0)
            expect(ticks.some((t) => /Jun \d+/.test(t))).toBe(true)
        })

        it('explicit xAxis.tickFormatter wins over the auto date formatter', () => {
            const explicit = (_v: string, i: number): string => `tick-${i}`
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={['2024-06-10', '2024-06-11', '2024-06-12']}
                    theme={THEME}
                    config={{
                        xAxis: {
                            tickFormatter: explicit,
                            timezone: 'UTC',
                            interval: 'day',
                        },
                    }}
                />
            )
            expect(chart.xTicks()).toEqual(['tick-0', 'tick-1', 'tick-2'])
        })

        it('exposes the resolved formatter to children via ChartLayoutContext', () => {
            let observed: ((value: string, index: number) => string | null) | undefined
            function Probe(): null {
                observed = useChartLayout().axis.xTickFormatter
                return null
            }
            renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={['2024-06-10', '2024-06-11', '2024-06-12']}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC', interval: 'day' } }}
                >
                    <Probe />
                </TimeSeriesBarChart>
            )
            expect(observed).not.toBeUndefined()
            expect(observed?.('2024-06-10', 0)).toMatch(/Jun \d+|June/)
        })
    })

    describe('config.yAxis', () => {
        it('hides y-axis ticks when yAxis.hide is true', () => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={THEME} config={{ yAxis: { hide: true } }} />
            )
            expect(chart.yTicks()).toHaveLength(0)
        })

        it.each([
            [{ format: 'percentage' as const }, /\d+%$/],
            [{ prefix: '$', suffix: ' req' }, /^\$.* req$/],
        ])('builds a y-axis tick formatter from yAxis %p', (yAxis, pattern) => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={THEME} config={{ yAxis }} />
            )
            expect(chart.yTicks().some((t) => pattern.test(t))).toBe(true)
        })

        it('explicit yAxis.tickFormatter wins over yAxis.format', () => {
            const explicit = (v: number): string => `y:${v}`
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        yAxis: {
                            tickFormatter: explicit,
                            format: 'percentage',
                        },
                    }}
                />
            )
            expect(chart.yTicks().every((t) => t.startsWith('y:'))).toBe(true)
        })
    })

    describe('config.valueLabels', () => {
        it.each([
            ['omitted', undefined],
            ['false', false as const],
        ])('does not render value labels when %s', (_, valueLabels) => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={valueLabels === undefined ? undefined : { valueLabels }}
                />
            )
            expect(chart.valueLabels()).toHaveLength(0)
        })

        it('renders one value label per visible point when valueLabels=true', () => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={THEME} config={{ valueLabels: true }} />
            )
            expect(chart.valueLabels()).toHaveLength(SERIES[0].data.length)
        })

        it('forwards an explicit formatter', () => {
            const formatter = (v: number): string => `~${v}`
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ valueLabels: { formatter } }}
                />
            )
            expect(chart.valueLabels().map((l) => l.text)).toEqual(['~1', '~2', '~3'])
        })

        it('falls back to a yAxis-driven formatter when no explicit formatter is provided', () => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={[{ key: 'a', label: 'A', data: [50] }]}
                    labels={['Mon']}
                    theme={THEME}
                    config={{
                        yAxis: { format: 'percentage' },
                        valueLabels: true,
                    }}
                />
            )
            expect(chart.valueLabels().map((l) => l.text)).toEqual(['50%'])
        })

        it('reuses an explicit yAxis.tickFormatter as the default', () => {
            const explicit = (v: number): string => `y:${v}`
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        yAxis: { tickFormatter: explicit },
                        valueLabels: true,
                    }}
                />
            )
            expect(chart.valueLabels().map((l) => l.text)).toEqual(['y:1', 'y:2', 'y:3'])
        })

        it('hides labels for series excluded via seriesKeys', () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [1, 2, 3] },
                { key: 'b', label: 'B', data: [4, 5, 6] },
            ]
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={series}
                    labels={LABELS}
                    theme={THEME}
                    config={{ valueLabels: { seriesKeys: ['a'] } }}
                />
            )
            expect(chart.valueLabels()).toHaveLength(3)
        })
    })

    describe('config.goalLines', () => {
        it.each([
            ['omitted', undefined],
            ['empty', [] as never[]],
        ])('does not render reference lines when goalLines is %s', (_, goalLines) => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={goalLines === undefined ? undefined : { goalLines }}
                />
            )
            expect(chart.referenceLines()).toHaveLength(0)
        })

        it('renders horizontal goal lines with their label', () => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={[{ key: 'a', label: 'A', data: [10, 20, 100] }]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ goalLines: [{ value: 50, label: 'Target' }] }}
                />
            )
            const lines = chart.referenceLines()
            expect(lines).toHaveLength(1)
            expect(lines[0].orientation).toBe('horizontal')
            expect(lines[0].label).toBe('Target')
        })

        it('extends the value axis so a goal line above the data still renders', () => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={[{ key: 'a', label: 'A', data: [10, 20, 30] }]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ goalLines: [{ value: 1000, label: 'Target' }] }}
                />
            )
            expect(chart.referenceLines()).toHaveLength(1)
        })
    })

    describe('config.barLayout', () => {
        it.each(['stacked', 'grouped', 'percent'] as const)('renders ticks for %s layout', (barLayout) => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30] },
                { key: 'b', label: 'B', data: [5, 15, 25] },
            ]
            const { chart } = renderHogChart(
                <TimeSeriesBarChart series={series} labels={LABELS} theme={THEME} config={{ barLayout }} />
            )
            expect(chart.yTicks().length).toBeGreaterThan(0)
        })

        it('applies a default percent formatter when barLayout=percent and no yAxis.format is given', () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [10, 20, 30] },
                { key: 'b', label: 'B', data: [5, 15, 25] },
            ]
            const { chart } = renderHogChart(
                <TimeSeriesBarChart series={series} labels={LABELS} theme={THEME} config={{ barLayout: 'percent' }} />
            )
            expect(chart.yTicks().some((t) => /\d+%/.test(t))).toBe(true)
        })

        it('formats value labels as each segment fraction (0..1) in percent layout', () => {
            // Two series with totals (10, 100, 1000); a's share is 0.1, 0.2, 0.3 of each band.
            // The `percentage_scaled` formatter takes 0..1 input so the labels render as "10%, 20%, 30%".
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={[
                        { key: 'a', label: 'A', data: [1, 20, 300] },
                        { key: 'b', label: 'B', data: [9, 80, 700] },
                    ]}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        barLayout: 'percent',
                        yAxis: { format: 'percentage_scaled' },
                        valueLabels: true,
                    }}
                />
            )
            // a's shares are [0.1, 0.2, 0.3]; b's are [0.9, 0.8, 0.7]. Sort so the assertion
            // doesn't depend on render order.
            expect(
                chart
                    .valueLabels()
                    .map((l) => l.text)
                    .sort()
            ).toEqual(['10%', '20%', '30%', '70%', '80%', '90%'].sort())
        })
    })

    describe('config.axisOrientation', () => {
        it('renders ticks on the x-axis when axisOrientation=horizontal', () => {
            const { chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ axisOrientation: 'horizontal' }}
                />
            )
            expect(chart.xTicks().length).toBeGreaterThan(0)
        })
    })

    it('forwards children alongside built-in overlays', () => {
        const { container } = renderHogChart(
            <TimeSeriesBarChart series={SERIES} labels={LABELS} theme={THEME}>
                <div data-attr="custom-overlay" />
            </TimeSeriesBarChart>
        )
        expect(container.querySelector('[data-attr="custom-overlay"]')).not.toBeNull()
    })

    describe('interactive legend', () => {
        it('toggles a series off and on when its legend row is clicked', () => {
            const { container, chart } = renderHogChart(
                <TimeSeriesBarChart
                    series={MULTI_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ legend: { show: true } }}
                />
            )
            expect(chart.seriesCount).toBe(2)
            const buttons = (): HTMLButtonElement[] =>
                Array.from(container.querySelectorAll('[data-attr="hog-chart-timeseries-bar-legend"] button'))

            fireEvent.click(buttons()[1])
            expect(getHogChart(container).seriesCount).toBe(1)

            fireEvent.click(buttons()[1])
            expect(getHogChart(container).seriesCount).toBe(2)
        })
    })
})

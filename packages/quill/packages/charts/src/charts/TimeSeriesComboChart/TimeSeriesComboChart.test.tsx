import { fireEvent } from '@testing-library/react'

import { useChartLayout } from '../../core/chart-context'
import type { ChartTheme, Series } from '../../core/types'
import { getHogChart, renderHogChart, waitForHogChartTooltip } from '../../testing'
import { TimeSeriesComboChart } from './TimeSeriesComboChart'

const THEME: ChartTheme = {
    colors: ['#111', '#222', '#333'],
    backgroundColor: '#ffffff',
}
const LABELS = ['Mon', 'Tue', 'Wed']
const BAR_AND_LINE: Series[] = [
    { key: 'bar', label: 'Bar', data: [40, 60, 50], type: 'bar' },
    { key: 'line', label: 'Line', data: [42, 55, 53], type: 'line' },
]

describe('TimeSeriesComboChart', () => {
    it('renders mixed bar + line series', () => {
        const { chart } = renderHogChart(<TimeSeriesComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} />)
        expect(chart.seriesCount).toBe(2)
        expect(chart.yTicks().length).toBeGreaterThan(0)
    })

    describe('config.xAxis', () => {
        it('hides x-axis ticks when xAxis.hide is true', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xAxis: { hide: true } }}
                />
            )
            expect(chart.xTicks()).toHaveLength(0)
        })

        it('forwards an explicit xAxis.tickFormatter to the chart', () => {
            const explicit = (_v: string, i: number): string => `tick-${i}`
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
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
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={labels}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC', interval: 'day' } }}
                />
            )
            const ticks = chart.xTicks()
            expect(ticks.length).toBeGreaterThan(0)
            expect(ticks.some((t) => /Jun \d+/.test(t))).toBe(true)
        })

        it('exposes the resolved formatter to children via ChartLayoutContext', () => {
            let observed: ((value: string, index: number) => string | null) | undefined
            function Probe(): null {
                observed = useChartLayout().axis.xTickFormatter
                return null
            }
            renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={['2024-06-10', '2024-06-11', '2024-06-12']}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC', interval: 'day' } }}
                >
                    <Probe />
                </TimeSeriesComboChart>
            )
            const formatter = observed as (value: string, index: number) => string | null
            expect(formatter('2024-06-10', 0)).toMatch(/Jun \d+|June/)
        })
    })

    describe('config.yAxis', () => {
        it('hides y-axis ticks when yAxis.hide is true', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { hide: true } }}
                />
            )
            expect(chart.yTicks()).toHaveLength(0)
        })

        it.each([
            [{ format: 'percentage' as const }, /\d+%$/],
            [{ prefix: '$', suffix: ' req' }, /^\$.* req$/],
        ])('builds a y-axis tick formatter from yAxis %p', (yAxis, pattern) => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} config={{ yAxis }} />
            )
            expect(chart.yTicks().some((t) => pattern.test(t))).toBe(true)
        })

        it('explicit yAxis.tickFormatter wins over yAxis.format', () => {
            const explicit = (v: number): string => `y:${v}`
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { tickFormatter: explicit, format: 'percentage' } }}
                />
            )
            expect(chart.yTicks().every((t) => t.startsWith('y:'))).toBe(true)
        })
    })

    describe('config.goalLines', () => {
        it('does not render reference lines when config is omitted', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} />
            )
            expect(chart.referenceLines()).toHaveLength(0)
        })

        it('does not render reference lines when goalLines is empty', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} config={{ goalLines: [] }} />
            )
            expect(chart.referenceLines()).toHaveLength(0)
        })

        it('renders horizontal goal lines with their label', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
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
                <TimeSeriesComboChart
                    series={[{ key: 'b', label: 'B', data: [10, 20, 30], type: 'bar' }]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ goalLines: [{ value: 1000, label: 'Target' }] }}
                />
            )
            expect(chart.referenceLines()).toHaveLength(1)
        })
    })

    describe('config.valueLabels', () => {
        it('does not render value labels when config is omitted', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} />
            )
            expect(chart.valueLabels()).toHaveLength(0)
        })

        it('does not render value labels when valueLabels is false', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ valueLabels: false }}
                />
            )
            expect(chart.valueLabels()).toHaveLength(0)
        })

        it('forwards an explicit formatter', () => {
            const formatter = (v: number): string => `~${v}`
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={[{ key: 'bar', label: 'Bar', data: [1, 2, 3], type: 'bar' }]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ valueLabels: { formatter } }}
                />
            )
            expect(chart.valueLabels().map((l) => l.text)).toEqual(['~1', '~2', '~3'])
        })
    })

    describe('config.barLayout', () => {
        // Two bar series (per-band sums up to 55) plus a small line, so the bars — not the line —
        // drive the value axis and stacked vs grouped produce a visibly different y-domain top.
        const STACKABLE: Series[] = [
            { key: 'a', label: 'A', data: [10, 20, 30], type: 'bar' },
            { key: 'b', label: 'B', data: [5, 15, 25], type: 'bar' },
            { key: 'l', label: 'L', data: [1, 1, 1], type: 'line' },
        ]
        const maxTick = (ticks: string[]): number => Math.max(...ticks.map(Number))

        it('stacks bar segments so the y-axis spans the stacked total', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={STACKABLE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ barLayout: 'stacked' }}
                />
            )
            expect(maxTick(chart.yTicks())).toBeGreaterThanOrEqual(55)
        })

        it('groups bars so the y-axis spans only the tallest single value', () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={STACKABLE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ barLayout: 'grouped' }}
                />
            )
            expect(maxTick(chart.yTicks())).toBeLessThan(55)
        })
    })

    it('renders a right axis when a series sets yAxisId: right', () => {
        const series: Series[] = [
            { key: 'b', label: 'Revenue', data: [1000, 2000, 1500], type: 'bar' },
            { key: 'l', label: 'Conv', data: [0.02, 0.03, 0.025], type: 'line', yAxisId: 'right' },
        ]
        const { chart } = renderHogChart(<TimeSeriesComboChart series={series} labels={LABELS} theme={THEME} />)
        expect(chart.hasRightAxis).toBe(true)
        expect(chart.yRightTicks().length).toBeGreaterThan(0)
    })

    it('forwards children alongside built-in overlays', () => {
        const { container } = renderHogChart(
            <TimeSeriesComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME}>
                <div data-attr="custom-overlay" />
            </TimeSeriesComboChart>
        )
        expect(container.querySelector('[data-attr="custom-overlay"]')).not.toBeNull()
    })

    describe('hover & tooltip', () => {
        it('lists every visible series at the hovered x', async () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart series={BAR_AND_LINE} labels={LABELS} theme={THEME} />
            )
            chart.hoverAtIndex(1)
            const tooltip = await chart.waitForTooltip()
            expect(tooltip.seriesData.map((s) => s.series.key).sort()).toEqual(['bar', 'line'])
        })

        // `nativeTooltip` lets the chart render its own DefaultTooltip from config (the harness's
        // default tooltip-prop interception would otherwise bypass the config formatters).
        it('formats the built-in tooltip rows with config.tooltip.valueFormatter', async () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ tooltip: { valueFormatter: (v) => `$${v}` } }}
                />,
                { nativeTooltip: true }
            )
            chart.hoverAtIndex(1)
            const tooltip = await waitForHogChartTooltip()
            expect(tooltip.textContent).toContain('$60')
        })

        it('appends a total row when config.tooltip.showTotal is set', async () => {
            const { chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ tooltip: { showTotal: true, totalLabel: 'Sum' } }}
                />,
                { nativeTooltip: true }
            )
            chart.hoverAtIndex(1)
            const tooltip = await waitForHogChartTooltip()
            expect(tooltip.textContent).toContain('Sum')
        })
    })

    describe('interactive legend', () => {
        it('toggles a series off and on when its legend row is clicked', () => {
            const { container, chart } = renderHogChart(
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={LABELS}
                    theme={THEME}
                    config={{ legend: { show: true } }}
                />
            )
            expect(chart.seriesCount).toBe(2)
            const buttons = (): HTMLButtonElement[] =>
                Array.from(container.querySelectorAll('[data-attr="hog-chart-timeseries-combo-legend"] button'))

            fireEvent.click(buttons()[1])
            expect(getHogChart(container).seriesCount).toBe(1)

            fireEvent.click(buttons()[1])
            expect(getHogChart(container).seriesCount).toBe(2)
        })
    })
})

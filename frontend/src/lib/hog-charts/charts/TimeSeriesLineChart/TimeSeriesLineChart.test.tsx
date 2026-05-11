import { cleanup } from '@testing-library/react'

import { useChartLayout } from '../../core/chart-context'
import type { ChartTheme, Series } from '../../core/types'
import { renderHogChart, setupJsdom, setupSyncRaf } from '../../testing'
import { TimeSeriesLineChart } from './TimeSeriesLineChart'

const THEME: ChartTheme = { colors: ['#111', '#222', '#333'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3] }]

describe('TimeSeriesLineChart', () => {
    let teardownJsdom: () => void
    let teardownRaf: () => void

    beforeEach(() => {
        teardownJsdom = setupJsdom()
        teardownRaf = setupSyncRaf()
    })

    afterEach(() => {
        teardownRaf()
        teardownJsdom()
        cleanup()
    })

    describe('config.xAxis', () => {
        it('hides x-axis ticks when xAxis.hide is true', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ xAxis: { hide: true } }} />
            )
            expect(chart.xTicks()).toHaveLength(0)
        })

        it('forwards an explicit xAxis.tickFormatter to the chart', () => {
            const explicit = (_v: string, i: number): string => `tick-${i}`
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
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
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                    labels={labels}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC', interval: 'day' } }}
                />
            )
            const ticks = chart.xTicks()
            expect(ticks.length).toBeGreaterThan(0)
            // The auto formatter renders day-mode labels as "MMM D" (or month name on the 1st).
            expect(ticks.some((t) => /Jun \d+/.test(t))).toBe(true)
        })

        it('explicit xAxis.tickFormatter wins over the auto date formatter', () => {
            const explicit = (_v: string, i: number): string => `tick-${i}`
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                    labels={['2024-06-10', '2024-06-11', '2024-06-12']}
                    theme={THEME}
                    config={{
                        xAxis: { tickFormatter: explicit, timezone: 'UTC', interval: 'day' },
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
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                    labels={['2024-06-10', '2024-06-11', '2024-06-12']}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC', interval: 'day' } }}
                >
                    <Probe />
                </TimeSeriesLineChart>
            )
            expect(observed).not.toBeUndefined()
            expect(observed?.('2024-06-10', 0)).toMatch(/Jun \d+|June/)
        })
    })

    describe('config.yAxis', () => {
        it('hides y-axis ticks when yAxis.hide is true', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ yAxis: { hide: true } }} />
            )
            expect(chart.yTicks()).toHaveLength(0)
        })

        it.each([
            [{ format: 'percentage' as const }, /\d+%$/],
            [{ prefix: '$', suffix: ' req' }, /^\$.* req$/],
        ])('builds a y-axis tick formatter from yAxis %p', (yAxis, pattern) => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ yAxis }} />
            )
            expect(chart.yTicks().some((t) => pattern.test(t))).toBe(true)
        })

        it('explicit yAxis.tickFormatter wins over yAxis.format', () => {
            const explicit = (v: number): string => `y:${v}`
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { tickFormatter: explicit, format: 'percentage' } }}
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
                <TimeSeriesLineChart
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
                <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ valueLabels: true }} />
            )
            expect(chart.valueLabels()).toHaveLength(SERIES[0].data.length)
        })

        it('forwards an explicit formatter', () => {
            const formatter = (v: number): string => `~${v}`
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
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
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [50] }]}
                    labels={['Mon']}
                    theme={THEME}
                    config={{ yAxis: { format: 'percentage' }, valueLabels: true }}
                />
            )
            expect(chart.valueLabels().map((l) => l.text)).toEqual(['50%'])
        })

        it('reuses an explicit yAxis.tickFormatter as the default', () => {
            const explicit = (v: number): string => `y:${v}`
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { tickFormatter: explicit }, valueLabels: true }}
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
                <TimeSeriesLineChart
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
                <TimeSeriesLineChart
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
                <TimeSeriesLineChart
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
    })

    describe('derived-series wiring', () => {
        it.each([
            ['confidenceIntervals', { confidenceIntervals: [{ seriesKey: 'a', lower: [0, 1, 2], upper: [2, 3, 4] }] }],
            ['movingAverage', { movingAverage: [{ seriesKey: 'a', window: 2 }] }],
            ['trendLines', { trendLines: [{ seriesKey: 'a', kind: 'linear' as const }] }],
        ])('plumbs config.%s through to the rendered series count', (_, derivedConfig) => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={derivedConfig} />
            )
            // SERIES has 1 entry; each derived block adds one more series.
            expect(chart.seriesCount).toBe(2)
        })

        it('skips comparison-period series count change while still rendering them', () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [1, 2, 3], color: '#112233' },
                { key: 'a-prev', label: 'A (prev)', data: [1, 2, 3], color: '#112233' },
            ]
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={series}
                    labels={LABELS}
                    theme={THEME}
                    config={{ comparisonOf: { 'a-prev': 'a' } }}
                />
            )
            expect(chart.seriesCount).toBe(2)
        })
    })

    it('forwards children alongside built-in overlays', () => {
        const { container } = renderHogChart(
            <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME}>
                <div data-attr="custom-overlay" />
            </TimeSeriesLineChart>
        )
        expect(container.querySelector('[data-attr="custom-overlay"]')).not.toBeNull()
    })
})

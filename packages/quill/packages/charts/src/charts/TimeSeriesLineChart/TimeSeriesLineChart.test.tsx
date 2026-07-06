import { cleanup, fireEvent } from '@testing-library/react'

import { useChartLayout } from '../../core/chart-context'
import type { ChartTheme, Series } from '../../core/types'
import { getHogChart, renderHogChart, setupJsdom, setupSyncRaf } from '../../testing'
import { TimeSeriesLineChart } from './TimeSeriesLineChart'

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

    describe('config.yAxis startAtZero', () => {
        // An offset, all-positive series: clamping to 0 leaves a big empty gutter below the data,
        // while floating zooms the axis onto the 50–70 band — so the lowest tick distinguishes them.
        const OFFSET_SERIES: Series[] = [{ key: 'a', label: 'A', data: [50, 60, 70] }]
        const lowestTick = (chart: ReturnType<typeof renderHogChart>['chart']): number =>
            Math.min(...chart.yTicks().map((t) => parseFloat(t.replace(/[^0-9.eE+-]/g, ''))))

        it.each([
            ['by default', undefined],
            ['when startAtZero is true', { yAxis: { startAtZero: true } }],
        ])('clamps the baseline to 0 %s', (_name, config) => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart series={OFFSET_SERIES} labels={LABELS} theme={THEME} config={config} />
            )
            expect(lowestTick(chart)).toBe(0)
        })

        it('floats the axis to the data range when startAtZero is false', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={OFFSET_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { startAtZero: false } }}
                />
            )
            expect(lowestTick(chart)).toBeGreaterThan(0)
        })

        it('ignores startAtZero=false on a log scale, where there is no zero baseline to drop', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={OFFSET_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { startAtZero: false, scale: 'log' } }}
                />
            )
            // A log axis can't include 0 regardless; this just guards against a crash / NaN domain.
            expect(lowestTick(chart)).toBeGreaterThan(0)
        })
    })

    describe('config.yAxis array (dual y-axis)', () => {
        const LEFT_RIGHT_SERIES: Series[] = [
            { key: 'rev', label: 'Revenue', data: [1000, 1500, 1200] },
            { key: 'conv', label: 'Conversion', data: [0.01, 0.02, 0.015], yAxisId: 'right' },
        ]
        const DUAL_CONFIG = { yAxis: [{ id: 'left' }, { id: 'right', position: 'right' as const }] }
        const num = (t: string): number => parseFloat(t.replace(/[^0-9.eE+-]/g, ''))

        it('renders both a left and a right y-axis when a series targets each', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart series={LEFT_RIGHT_SERIES} labels={LABELS} theme={THEME} config={DUAL_CONFIG} />
            )
            expect(chart.hasRightAxis).toBe(true)
            expect(chart.yTicks().length).toBeGreaterThan(0)
            expect(chart.yRightTicks().length).toBeGreaterThan(0)
        })

        it('hides only the right axis when its entry sets hide, keeping the left axis', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={LEFT_RIGHT_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: [{ id: 'left' }, { id: 'right', position: 'right', hide: true }] }}
                />
            )
            expect(chart.yTicks().length).toBeGreaterThan(0)
            expect(chart.yRightTicks()).toHaveLength(0)
        })

        it('collapses the y-axis gutter only when every entry sets hide', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={LEFT_RIGHT_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        yAxis: [
                            { id: 'left', hide: true },
                            { id: 'right', position: 'right', hide: true },
                        ],
                    }}
                />
            )
            expect(chart.yTicks()).toHaveLength(0)
        })

        it('formats each axis with its own tick formatter', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={LEFT_RIGHT_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        yAxis: [
                            { id: 'left', tickFormatter: (v) => `L${v}` },
                            { id: 'right', position: 'right', tickFormatter: (v) => `R${v}` },
                        ],
                    }}
                />
            )
            expect(chart.yTicks().every((t) => t.startsWith('L'))).toBe(true)
            expect(chart.yRightTicks().every((t) => t.startsWith('R'))).toBe(true)
        })

        it('builds an independent scale per axis — left covers the large series, right the small one', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={LEFT_RIGHT_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        yAxis: [
                            { id: 'left', tickFormatter: (v) => `L${v}` },
                            { id: 'right', position: 'right', tickFormatter: (v) => `R${v}` },
                        ],
                    }}
                />
            )
            expect(Math.max(...chart.yTicks().map(num))).toBeGreaterThanOrEqual(1000)
            expect(Math.max(...chart.yRightTicks().map(num))).toBeLessThanOrEqual(1)
        })

        it('renders a title per axis, each from its own entry label', () => {
            const threeAxisSeries: Series[] = [
                { key: 'rev', label: 'Revenue', data: [1000, 1500, 1200] },
                { key: 'signups', label: 'Signups', data: [50, 80, 65], yAxisId: 'right' },
                { key: 'conv', label: 'Conversion', data: [0.01, 0.02, 0.015], yAxisId: 'right2' },
            ]
            const { container, chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={threeAxisSeries}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        yAxis: [
                            { id: 'left', label: 'Revenue' },
                            { id: 'right', position: 'right', label: 'Signups' },
                            { id: 'right2', position: 'right', label: 'Conversion' },
                        ],
                    }}
                />
            )
            const rightTitles = Array.from(
                container.querySelectorAll<SVGTextElement>('[data-attr="hog-chart-axis-title-yr"]')
            ).map((el) => el.textContent)
            expect(chart.yAxisLabel()).toBe('Revenue')
            expect(rightTitles).toEqual(['Signups', 'Conversion'])
        })

        it('reserves right margin so right-axis tick labels are not clipped', () => {
            const { container } = renderHogChart(
                <TimeSeriesLineChart
                    series={LEFT_RIGHT_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        yAxis: [
                            { id: 'left' },
                            { id: 'right', position: 'right', tickFormatter: (v) => `${v} requests/s` },
                        ],
                    }}
                />
            )
            const rightTicks = Array.from(
                container.querySelectorAll<HTMLElement>('[data-attr="hog-chart-axis-tick-yr"]')
            )
            expect(rightTicks.length).toBeGreaterThan(0)
            // The mocked canvas is 800px wide; each right-gutter label sits inside it with room to spare.
            for (const el of rightTicks) {
                const left = parseFloat(el.style.left)
                expect(Number.isFinite(left)).toBe(true)
                expect(left).toBeLessThan(800)
                expect(800 - left).toBeGreaterThanOrEqual(12)
            }
        })

        it('treats a single-object yAxis as one axis (no right gutter) — back-compat', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { format: 'percentage' } }}
                />
            )
            expect(chart.hasRightAxis).toBe(false)
            expect(chart.yRightTicks()).toHaveLength(0)
        })

        it('does not render a right axis when an array config has no right-axis series', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={DUAL_CONFIG} />
            )
            expect(chart.hasRightAxis).toBe(false)
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
                <TimeSeriesLineChart
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

        it('extends the value axis so a goal line above the data still renders', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [10, 20, 30] }]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ goalLines: [{ value: 1000, label: 'Target' }] }}
                />
            )
            expect(chart.referenceLines()).toHaveLength(1)
        })
    })

    describe('derived-series wiring', () => {
        it.each([
            [
                'confidenceIntervals',
                {
                    confidenceIntervals: [{ seriesKey: 'a', lower: [0, 1, 2], upper: [2, 3, 4] }],
                },
            ],
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
                {
                    key: 'a-prev',
                    label: 'A (prev)',
                    data: [1, 2, 3],
                    color: '#112233',
                },
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

    describe('interactive legend', () => {
        it('lists the raw series (not derived trend lines) and toggles one off on click', () => {
            const { container, chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={MULTI_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{
                        legend: { show: true },
                        trendLines: [{ seriesKey: 'a', kind: 'linear' as const }],
                    }}
                />
            )
            const buttons = (): HTMLButtonElement[] =>
                Array.from(container.querySelectorAll('[data-attr="hog-chart-timeseries-line-legend"] button'))
            // The legend lists only the user's series, not the derived trend line.
            expect(buttons().map((b) => b.textContent)).toEqual(['A', 'B'])

            // A + B + trend-of-A are all drawn before any toggle.
            expect(chart.seriesCount).toBe(3)
            fireEvent.click(buttons()[0])
            // Hiding A also suppresses its trend line, leaving only B.
            expect(getHogChart(container).seriesCount).toBe(1)
        })
    })
})

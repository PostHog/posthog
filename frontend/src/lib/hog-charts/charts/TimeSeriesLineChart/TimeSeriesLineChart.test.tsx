import { cleanup } from '@testing-library/react'

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

        it('builds an x-axis tick formatter from xAxis.timezone + xAxis.interval', () => {
            const allDays = ['2025-04-01 14:00:00', '2025-04-01 15:00:00', '2025-04-01 16:00:00']
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                    labels={['14:00', '15:00', '16:00']}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC', interval: 'hour', allDays } }}
                />
            )
            expect(chart.xTicks()).toEqual(['14:00', '15:00', '16:00'])
        })

        it('explicit xAxis.tickFormatter wins over timezone+interval', () => {
            const explicit = (_v: string, i: number): string => `tick-${i}`
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                    labels={['14:00', '15:00', '16:00']}
                    theme={THEME}
                    config={{
                        xAxis: {
                            tickFormatter: explicit,
                            timezone: 'UTC',
                            interval: 'hour',
                            allDays: ['2025-04-01 14:00:00', '2025-04-01 15:00:00', '2025-04-01 16:00:00'],
                        },
                    }}
                />
            )
            expect(chart.xTicks()).toEqual(['tick-0', 'tick-1', 'tick-2'])
        })

        it('does not auto-format when only one of timezone or interval is provided', () => {
            const { chart } = renderHogChart(
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ xAxis: { timezone: 'UTC' } }}
                />
            )
            expect(chart.xTicks()).toEqual(LABELS)
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

    it('forwards children alongside built-in overlays', () => {
        const { container } = renderHogChart(
            <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME}>
                <div data-attr="custom-overlay" />
            </TimeSeriesLineChart>
        )
        expect(container.querySelector('[data-attr="custom-overlay"]')).not.toBeNull()
    })
})

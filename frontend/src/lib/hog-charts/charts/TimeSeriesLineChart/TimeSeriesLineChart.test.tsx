import { render } from '@testing-library/react'

import type { ChartTheme, Series } from '../../core/types'
import type { ReferenceLineProps } from '../../overlays/ReferenceLine'
import type { ValueLabelsProps } from '../../overlays/ValueLabels'
import type { LineChartProps } from '../LineChart'

const lineChartSpy = jest.fn()
const referenceLinesSpy = jest.fn()
const valueLabelsSpy = jest.fn()

jest.mock('../LineChart', () => ({
    LineChart: (props: LineChartProps) => {
        lineChartSpy(props)
        return <div data-attr="line-chart-mock">{props.children}</div>
    },
}))

jest.mock('../../overlays/ReferenceLine', () => ({
    ReferenceLines: (props: { lines: ReferenceLineProps[] }) => {
        referenceLinesSpy(props)
        return <div data-attr="reference-lines-mock" />
    },
}))

jest.mock('../../overlays/ValueLabels', () => ({
    ValueLabels: (props: ValueLabelsProps) => {
        valueLabelsSpy(props)
        return <div data-attr="value-labels-mock" />
    },
}))

import { TimeSeriesLineChart } from './TimeSeriesLineChart'

const THEME: ChartTheme = { colors: ['#111', '#222', '#333'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3] }]

describe('TimeSeriesLineChart', () => {
    beforeEach(() => {
        lineChartSpy.mockClear()
        referenceLinesSpy.mockClear()
        valueLabelsSpy.mockClear()
    })

    it('translates config.xAxis and config.yAxis fields onto LineChartConfig', () => {
        const xTickFormatter = (v: string): string => `x:${v}`
        const yTickFormatter = (v: number): string => `y:${v}`
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{
                    xAxis: { tickFormatter: xTickFormatter, hide: true },
                    yAxis: { scale: 'log', tickFormatter: yTickFormatter, hide: true, showGrid: true },
                }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.labels).toBe(LABELS)
        expect(props.config?.yScaleType).toBe('log')
        expect(props.config?.xTickFormatter).toBe(xTickFormatter)
        expect(props.config?.yTickFormatter).toBe(yTickFormatter)
        expect(props.config?.hideXAxis).toBe(true)
        expect(props.config?.hideYAxis).toBe(true)
        expect(props.config?.showGrid).toBe(true)
    })

    it('builds an x-axis tick formatter from xAxis.timezone + xAxis.interval', () => {
        const allDays = ['2025-04-01 14:00:00', '2025-04-01 15:00:00', '2025-04-01 16:00:00']
        render(
            <TimeSeriesLineChart
                series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                labels={['14:00', '15:00', '16:00']}
                theme={THEME}
                config={{
                    xAxis: { timezone: 'UTC', interval: 'hour', allDays },
                }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        const formatter = props.config?.xTickFormatter
        expect(formatter).not.toBeUndefined()
        expect(formatter?.('ignored', 0)).toBe('14:00')
        expect(formatter?.('ignored', 1)).toBe('15:00')
        expect(formatter?.('ignored', 2)).toBe('16:00')
    })

    it('explicit tickFormatter wins over xAxis.timezone + xAxis.interval', () => {
        const explicit = (_v: string, i: number): string => `tick-${i}`
        render(
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
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.xTickFormatter).toBe(explicit)
    })

    it('builds a y-axis tick formatter from yAxis.format', () => {
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ yAxis: { format: 'percentage' } }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        const formatter = props.config?.yTickFormatter
        expect(formatter).not.toBeUndefined()
        expect(formatter?.(50)).toBe('50%')
    })

    it('builds a y-axis tick formatter from yAxis.prefix/suffix without format', () => {
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ yAxis: { prefix: '$', suffix: ' req' } }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.yTickFormatter?.(42)).toBe('$42 req')
    })

    it('explicit yAxis.tickFormatter wins over yAxis.format', () => {
        const explicit = (v: number): string => `y:${v}`
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ yAxis: { tickFormatter: explicit, format: 'percentage' } }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.yTickFormatter).toBe(explicit)
    })

    it('does not build a y-axis tick formatter when no format options are set', () => {
        render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ yAxis: {} }} />)
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.yTickFormatter).toBeUndefined()
    })

    it('does not auto-format when only one of timezone or interval is provided', () => {
        render(
            <TimeSeriesLineChart
                series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                labels={LABELS}
                theme={THEME}
                config={{
                    xAxis: { timezone: 'UTC' },
                }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.xTickFormatter).toBeUndefined()
    })

    describe('config.inProgress', () => {
        it('sets stroke.partial.fromIndex on each series when configured', () => {
            render(
                <TimeSeriesLineChart
                    series={[
                        { key: 'a', label: 'A', data: [1, 2, 3, 4] },
                        { key: 'b', label: 'B', data: [5, 6, 7, 8] },
                    ]}
                    labels={['Mon', 'Tue', 'Wed', 'Thu']}
                    theme={THEME}
                    config={{ inProgress: { fromIndex: 2 } }}
                />
            )
            const props = lineChartSpy.mock.calls[0][0] as LineChartProps
            expect(props.series[0].stroke?.partial?.fromIndex).toBe(2)
            expect(props.series[1].stroke?.partial?.fromIndex).toBe(2)
        })

        it("preserves a series' explicit stroke.partial when inProgress is set", () => {
            const explicitPartial = { fromIndex: 99, pattern: [4, 4] as number[] }
            render(
                <TimeSeriesLineChart
                    series={[{ key: 'a', label: 'A', data: [1, 2, 3], stroke: { partial: explicitPartial } }]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ inProgress: { fromIndex: 1 } }}
                />
            )
            const props = lineChartSpy.mock.calls[0][0] as LineChartProps
            expect(props.series[0].stroke?.partial).toBe(explicitPartial)
        })

        it('leaves series untouched when inProgress is omitted', () => {
            render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} />)
            const props = lineChartSpy.mock.calls[0][0] as LineChartProps
            expect(props.series).toBe(SERIES)
        })
    })

    describe('config.valueLabels', () => {
        it('does not render ValueLabels when omitted or false', () => {
            render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} />)
            expect(valueLabelsSpy).not.toHaveBeenCalled()

            render(
                <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ valueLabels: false }} />
            )
            expect(valueLabelsSpy).not.toHaveBeenCalled()
        })

        it('renders ValueLabels with no formatter when valueLabels=true and yAxis has no format', () => {
            render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ valueLabels: true }} />)
            expect(valueLabelsSpy).toHaveBeenCalledTimes(1)
            expect(valueLabelsSpy.mock.calls[0][0].valueFormatter).toBeUndefined()
        })

        it('forwards an explicit formatter unchanged in behaviour', () => {
            const formatter = (v: number): string => `~${v}`
            render(
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ valueLabels: { formatter } }}
                />
            )
            const valueFormatter = valueLabelsSpy.mock.calls[0][0].valueFormatter
            expect(valueFormatter?.(7, 0, 0)).toBe('~7')
        })

        it('falls back to a yAxis-driven formatter when no explicit formatter is provided', () => {
            render(
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ yAxis: { format: 'percentage' }, valueLabels: true }}
                />
            )
            const valueFormatter = valueLabelsSpy.mock.calls[0][0].valueFormatter
            expect(valueFormatter?.(50, 0, 0)).toBe('50%')
        })

        it('marks non-allowed series as excluded from value labels via visibility.fromValueLabels', () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [1, 2, 3] },
                { key: 'b', label: 'B', data: [4, 5, 6] },
            ]
            render(
                <TimeSeriesLineChart
                    series={series}
                    labels={LABELS}
                    theme={THEME}
                    config={{ valueLabels: { seriesKeys: ['a'] } }}
                />
            )
            const props = lineChartSpy.mock.calls[0][0] as LineChartProps
            expect(props.series[0].visibility?.fromValueLabels).toBeFalsy()
            expect(props.series[1].visibility?.fromValueLabels).toBe(true)
        })
    })

    describe('config.goalLines', () => {
        it('does not render ReferenceLines when goalLines is omitted or empty', () => {
            render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} />)
            expect(referenceLinesSpy).not.toHaveBeenCalled()

            render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ goalLines: [] }} />)
            expect(referenceLinesSpy).not.toHaveBeenCalled()
        })

        it('renders ReferenceLines with horizontal goal-variant lines', () => {
            render(
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ goalLines: [{ value: 50, label: 'Target' }] }}
                />
            )
            expect(referenceLinesSpy).toHaveBeenCalledTimes(1)
            const lines = referenceLinesSpy.mock.calls[0][0].lines as ReferenceLineProps[]
            expect(lines).toHaveLength(1)
            expect(lines[0]).toMatchObject({
                value: 50,
                orientation: 'horizontal',
                variant: 'goal',
                label: 'Target',
                labelPosition: 'start',
            })
        })
    })

    it('forwards children alongside built-in overlays', () => {
        const { container } = render(
            <TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME}>
                <div data-attr="custom-overlay" />
            </TimeSeriesLineChart>
        )
        expect(container.querySelector('[data-attr="custom-overlay"]')).not.toBeNull()
    })
})

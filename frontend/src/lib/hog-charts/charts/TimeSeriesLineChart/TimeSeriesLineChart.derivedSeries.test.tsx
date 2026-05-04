import { render } from '@testing-library/react'

import type { ChartTheme, Series } from '../../core/types'
import type { LineChartProps } from '../LineChart'
import { TimeSeriesLineChart } from './TimeSeriesLineChart'

// Stub LineChart so the test sees exactly the series array TimeSeriesLineChart
// produces, without canvas measurement or layout work.
jest.mock('../LineChart', () => {
    const calls: LineChartProps<unknown>[] = []
    return {
        __esModule: true,
        LineChart: (props: LineChartProps<unknown>) => {
            calls.push(props)
            return null
        },
        // Test-only handle so individual cases can grab the most recent props.
        __getLastProps: () => calls[calls.length - 1],
        __reset: () => {
            calls.length = 0
        },
    }
})

const lineChartModule = jest.requireMock('../LineChart') as {
    __getLastProps: () => LineChartProps<unknown> | undefined
    __reset: () => void
}

const THEME: ChartTheme = { colors: ['#111', '#222', '#333'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue', 'Wed', 'Thu']
const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3, 4], color: '#112233' },
    { key: 'b', label: 'B', data: [5, 6, 7, 8], color: '#445566' },
]

function renderAndCapture(config?: Parameters<typeof TimeSeriesLineChart>[0]['config']): Series[] {
    lineChartModule.__reset()
    render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={config} />)
    const props = lineChartModule.__getLastProps()
    if (!props) {
        throw new Error('LineChart was not rendered')
    }
    return props.series as Series[]
}

describe('TimeSeriesLineChart — derived series wiring', () => {
    it('passes the original series through when no derived-series props are set', () => {
        const passed = renderAndCapture()
        expect(passed.map((s) => s.key)).toEqual(['a', 'b'])
    })

    describe('config.confidenceIntervals', () => {
        it('inserts a CI band before the main series and matches the source styling', () => {
            const passed = renderAndCapture({
                confidenceIntervals: [{ seriesKey: 'a', lower: [0, 1, 2, 3], upper: [2, 3, 4, 5] }],
            })
            // CI bands paint behind the main lines — they sit at the front of the array.
            expect(passed.map((s) => s.key)).toEqual(['a__ci', 'a', 'b'])
            const ci = passed[0]
            expect(ci.fill?.lowerData).toEqual([0, 1, 2, 3])
            expect(ci.color).toBe('#112233')
            expect(ci.label).toBe('A (CI)')
        })

        it('is a no-op when the prop is absent', () => {
            expect(renderAndCapture().some((s) => s.key.endsWith('__ci'))).toBe(false)
        })
    })

    describe('config.movingAverage', () => {
        it('appends a moving-average series after the main lines', () => {
            const passed = renderAndCapture({ movingAverage: [{ seriesKey: 'a', window: 2 }] })
            expect(passed.map((s) => s.key)).toEqual(['a', 'b', 'a-ma'])
            expect(passed[2].stroke?.pattern).not.toBeUndefined()
            expect(passed[2].visibility?.fromStack).toBe(true)
        })

        it('is a no-op when the prop is absent', () => {
            expect(renderAndCapture().some((s) => s.key.endsWith('-ma'))).toBe(false)
        })
    })

    describe('config.trendLines', () => {
        it('appends a trend-line series after moving averages', () => {
            const passed = renderAndCapture({
                movingAverage: [{ seriesKey: 'a', window: 2 }],
                trendLines: [{ seriesKey: 'a', kind: 'linear' }],
            })
            // Order matters for paint: CI < main < MA < trend lines.
            expect(passed.map((s) => s.key)).toEqual(['a', 'b', 'a-ma', 'a__trendline'])
        })

        it('is a no-op when the prop is absent', () => {
            expect(renderAndCapture().some((s) => s.key.endsWith('__trendline'))).toBe(false)
        })
    })

    describe('config.comparisonOf', () => {
        it('rewrites comparison series colours to a dimmed rgba string', () => {
            const series: Series[] = [
                { key: 'a', label: 'A', data: [1, 2, 3, 4], color: '#112233' },
                { key: 'a-prev', label: 'A (prev)', data: [1, 2, 3, 4], color: '#112233' },
            ]
            lineChartModule.__reset()
            render(
                <TimeSeriesLineChart
                    series={series}
                    labels={LABELS}
                    theme={THEME}
                    config={{ comparisonOf: { 'a-prev': 'a' } }}
                />
            )
            const passed = lineChartModule.__getLastProps()!.series as Series[]
            expect(passed[0].color).toBe('#112233')
            expect(passed[1].color).toMatch(/^rgba\([^)]*,\s*0\.5\)$/)
        })

        it('is a no-op when the prop is absent', () => {
            const passed = renderAndCapture()
            expect(passed.every((s) => !s.color || s.color.startsWith('#'))).toBe(true)
        })
    })
})

import { cleanup } from '@testing-library/react'
import React from 'react'

import type { ChartTheme, Series } from '../../core/types'
import { getHogChartTooltip, renderHogChart, setupJsdom, setupSyncRaf } from '../../testing'
import { TimeSeriesBarChart } from '../TimeSeriesBarChart/TimeSeriesBarChart'
import { TimeSeriesLineChart } from '../TimeSeriesLineChart/TimeSeriesLineChart'

const THEME: ChartTheme = {
    colors: ['#111', '#222', '#333'],
    backgroundColor: '#ffffff',
}
const LABELS = ['2024-06-10', '2024-06-11', '2024-06-12']
const SERIES: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3] },
    { key: 'b', label: 'B', data: [3, 2, 1] },
]
const DATE_AXIS = { xAxis: { timezone: 'UTC', interval: 'day' as const } }

describe('time-series chart loading states', () => {
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

    describe.each([
        { name: 'TimeSeriesLineChart', Component: TimeSeriesLineChart },
        { name: 'TimeSeriesBarChart', Component: TimeSeriesBarChart },
    ])('$name', ({ Component }) => {
        it('loading renders the skeleton with real x ticks, hidden y ticks, and no tooltip', async () => {
            const { chart, container } = renderHogChart(
                <Component series={[]} labels={LABELS} theme={THEME} loading config={DATE_AXIS} />
            )
            expect(chart.seriesCount).toBe(1)
            expect(chart.xTicks().some((t) => /Jun \d+/.test(t))).toBe(true)
            expect(chart.yTicks().filter(Boolean)).toHaveLength(0)
            expect(container.querySelector('[data-attr="hog-chart-loading-overlay"]')).not.toBeNull()

            chart.hoverAtIndex(1)
            await new Promise((r) => setTimeout(r, 50))
            expect(getHogChartTooltip()).toBeNull()
        })

        it('refreshing keeps the real series rendered with the overlay and no tooltip', async () => {
            const { chart, container } = renderHogChart(
                <Component series={SERIES} labels={LABELS} theme={THEME} refreshing config={DATE_AXIS} />
            )
            expect(chart.seriesCount).toBe(SERIES.length)
            expect(container.querySelector('[data-attr="hog-chart-loading-overlay"]')).not.toBeNull()

            chart.hoverAtIndex(1)
            await new Promise((r) => setTimeout(r, 50))
            expect(getHogChartTooltip()).toBeNull()
        })

        it('renders normally when neither loading nor refreshing', () => {
            const { chart, container } = renderHogChart(
                <Component series={SERIES} labels={LABELS} theme={THEME} config={DATE_AXIS} />
            )
            expect(chart.seriesCount).toBe(SERIES.length)
            expect(chart.yTicks().filter(Boolean).length).toBeGreaterThan(0)
            expect(container.querySelector('[data-attr="hog-chart-loading-overlay"]')).toBeNull()
        })
    })
})

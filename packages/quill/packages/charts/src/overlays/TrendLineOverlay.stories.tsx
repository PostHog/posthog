import { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesBarChart } from '../charts/TimeSeriesBarChart/TimeSeriesBarChart'
import type { Series } from '../core/types'
import { Stage, useReactiveTheme } from '../story-helpers'

const LABELS = ['2024-01', '2024-02', '2024-03', '2024-04', '2024-05', '2024-06']

const meta: Meta = {
    title: 'Components/HogCharts/TrendLineOverlay',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

/** Single bar series with an upward linear trend line rendered as an SVG overlay. */
export const SingleSeriesWithTrend: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'revenue', label: 'Revenue', color: '#7c3aed', data: [120, 180, 150, 220, 200, 260] },
        ]
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={series}
                    labels={LABELS}
                    theme={theme}
                    config={{
                        barLayout: 'grouped',
                        yAxis: { showGrid: true },
                        trendLines: [{ seriesKey: 'revenue', kind: 'linear' }],
                    }}
                />
            </Stage>
        )
    },
}

/** Two stacked series each with their own trend line — trend lines respect series colour and are
 *  clipped to the plot area. */
export const StackedWithTrendLines: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'a', label: 'Product A', color: '#059669', data: [80, 100, 90, 130, 110, 150] },
            { key: 'b', label: 'Product B', color: '#db2777', data: [40, 60, 70, 90, 80, 110] },
        ]
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={series}
                    labels={LABELS}
                    theme={theme}
                    config={{
                        barLayout: 'stacked',
                        yAxis: { showGrid: true },
                        trendLines: [
                            { seriesKey: 'a', kind: 'linear' },
                            { seriesKey: 'b', kind: 'linear' },
                        ],
                    }}
                />
            </Stage>
        )
    },
}

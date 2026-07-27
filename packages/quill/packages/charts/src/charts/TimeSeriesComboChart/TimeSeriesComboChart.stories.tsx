import { Meta, StoryObj } from '@storybook/react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { MONTHLY_LABELS } from '../time-series-fixtures'
import { TimeSeriesComboChart } from './TimeSeriesComboChart'

const meta: Meta = {
    title: 'Components/HogCharts/TimeSeriesComboChart',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

const BAR_AND_LINE: Series[] = [
    { key: 'visits', label: 'Visits', data: [120, 135, 150, 142, 200, 220, 245, 260, 275, 290, 310, 330], type: 'bar' },
    {
        key: 'rolling',
        label: 'Rolling avg',
        data: [110, 125, 140, 145, 180, 205, 230, 250, 268, 282, 300, 320],
        type: 'line',
    },
]

export const Basic: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={MONTHLY_LABELS}
                    theme={theme}
                    config={{
                        xAxis: { timezone: 'UTC', interval: 'month' },
                        yAxis: { showGrid: true },
                        legend: { show: true },
                    }}
                />
            </Stage>
        )
    },
}

export const StackedBarsAndLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            {
                key: 'desktop',
                label: 'Desktop',
                data: [70, 80, 90, 85, 120, 130, 145, 150, 160, 170, 185, 195],
                type: 'bar',
            },
            {
                key: 'mobile',
                label: 'Mobile',
                data: [50, 55, 60, 57, 80, 90, 100, 110, 115, 120, 125, 135],
                type: 'bar',
            },
            {
                key: 'total',
                label: 'Total (rolling)',
                data: [120, 135, 150, 142, 200, 220, 245, 260, 275, 290, 310, 330],
                type: 'line',
            },
        ]
        return (
            <Stage>
                <TimeSeriesComboChart
                    series={series}
                    labels={MONTHLY_LABELS}
                    theme={theme}
                    config={{
                        xAxis: { timezone: 'UTC', interval: 'month' },
                        yAxis: { showGrid: true },
                        barLayout: 'stacked',
                        legend: { show: true },
                    }}
                />
            </Stage>
        )
    },
}

/** A goal line above the data range stretches the value axis so it still renders on-plot. */
export const WithGoalLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesComboChart
                    series={BAR_AND_LINE}
                    labels={MONTHLY_LABELS}
                    theme={theme}
                    config={{
                        xAxis: { timezone: 'UTC', interval: 'month' },
                        yAxis: { showGrid: true },
                        goalLines: [{ value: 400, label: 'Target' }],
                    }}
                />
            </Stage>
        )
    },
}

/** Bars on the left axis, a line on the right — independent y-axes. */
export const DualYAxis: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                data: [1100, 1300, 1250, 1700, 1500, 1900, 1800, 2100, 2200, 2400, 2600, 2800],
                type: 'bar',
            },
            {
                key: 'conversion',
                label: 'Conversion',
                data: [0.022, 0.028, 0.025, 0.034, 0.031, 0.038, 0.036, 0.04, 0.042, 0.045, 0.047, 0.05],
                type: 'line',
                yAxisId: 'right',
            },
        ]
        return (
            <Stage>
                <TimeSeriesComboChart
                    series={series}
                    labels={MONTHLY_LABELS}
                    theme={theme}
                    config={{
                        xAxis: { timezone: 'UTC', interval: 'month' },
                        yAxis: { showGrid: true },
                        legend: { show: true },
                    }}
                />
            </Stage>
        )
    },
}

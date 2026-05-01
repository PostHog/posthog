import { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesLineChart } from 'lib/hog-charts'
import type { Series } from 'lib/hog-charts'

import { Stage, useReactiveTheme } from '../../story-helpers'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const SERIES: Series[] = [
    { key: 'visits', label: 'Visits', data: [20, 35, 28, 60, 45, 70, 52] },
    { key: 'signups', label: 'Sign-ups', data: [4, 8, 6, 14, 11, 19, 13] },
    { key: 'activations', label: 'Activations', data: [2, 5, 4, 9, 7, 12, 8] },
]

const meta: Meta = {
    title: 'Components/HogCharts/TimeSeriesLineChart',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const Basic: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

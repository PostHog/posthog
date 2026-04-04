import type { Meta, StoryObj } from '@storybook/react'

import { LineChart, type LineChartProps } from './charts/LineChart'
import type { ChartTheme, Series } from './core/types'

const THEME: ChartTheme = {
    colors: ['#1d4aff', '#cd0f74', '#43827e', '#621da6', '#f04f58', '#f1a82c'],
    axisColor: '#c3cad2',
    gridColor: '#e9ecef',
    crosshairColor: '#888',
    backgroundColor: '#fff',
}

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const BASE_SERIES: Series[] = [
    { key: 'pageviews', label: 'Pageviews', data: [120, 200, 150, 300, 280, 220, 180], color: '#1d4aff' },
    { key: 'signups', label: 'Signups', data: [10, 25, 18, 40, 35, 28, 22], color: '#cd0f74' },
]

type Story = StoryObj<LineChartProps>

const meta: Meta<LineChartProps> = {
    title: 'Components/HogCharts/LineChart',
    component: LineChart,
    render: (args) => <LineChart {...args} />,
}
export default meta

export const Default: Story = {
    args: {
        series: BASE_SERIES,
        labels: LABELS,
        theme: THEME,
        config: { showTooltip: true, showCrosshair: true, showGrid: true },
        className: 'h-80',
    },
}

export const TooltipInScrollContainer: Story = {
    render: () => (
        <div style={{ width: 400, height: 300, overflow: 'auto', border: '1px solid #ccc', padding: 16 }}>
            <div style={{ width: 800, height: 500 }}>
                <LineChart
                    series={BASE_SERIES}
                    labels={LABELS}
                    theme={THEME}
                    config={{ showTooltip: true, showCrosshair: true }}
                    className="h-full"
                />
            </div>
        </div>
    ),
}

export const TooltipNearRightEdge: Story = {
    render: () => (
        <div className="flex justify-end" style={{ width: '100%' }}>
            <div style={{ width: 300 }}>
                <LineChart
                    series={[
                        {
                            key: 'data',
                            label: 'Values',
                            data: [5, 10, 20, 50, 100, 200, 500],
                            color: '#1d4aff',
                        },
                    ]}
                    labels={LABELS}
                    theme={THEME}
                    config={{ showTooltip: true, showCrosshair: true }}
                    className="h-60"
                />
            </div>
        </div>
    ),
}

export const TooltipNearTopEdge: Story = {
    render: () => (
        <div style={{ width: 500, marginTop: 0 }}>
            <LineChart
                series={[
                    {
                        key: 'spike',
                        label: 'Spike at start',
                        data: [1000, 50, 30, 20, 15, 10, 5],
                        color: '#43827e',
                    },
                ]}
                labels={LABELS}
                theme={THEME}
                config={{ showTooltip: true, showCrosshair: true }}
                className="h-48"
            />
        </div>
    ),
}

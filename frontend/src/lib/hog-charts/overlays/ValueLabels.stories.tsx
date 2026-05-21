import { Meta, StoryObj } from '@storybook/react'

import { LineChart, ValueLabels } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'

import { Stage, useReactiveTheme } from '../story-helpers'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const CONFIG: LineChartConfig = {
    showGrid: true,
    showCrosshair: false,
}

const meta: Meta = {
    title: 'Components/HogCharts/ValueLabels',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const SingleSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'visits', label: 'Visits', color: '', data: [20, 35, 28, 60, 45, 70, 52], points: { radius: 3 } },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme}>
                    <ValueLabels />
                </LineChart>
            </Stage>
        )
    },
}

export const MultiSeriesCollision: Story = {
    render: () => {
        const theme = useReactiveTheme()
        // Three dense series with values close enough in places that collision
        // avoidance should visibly drop some labels.
        const series: Series[] = [
            { key: 'desktop', label: 'Desktop', color: '', data: [40, 42, 44, 43, 45, 47, 46], points: { radius: 3 } },
            { key: 'mobile', label: 'Mobile', color: '', data: [38, 41, 40, 44, 46, 48, 47], points: { radius: 3 } },
            { key: 'tablet', label: 'Tablet', color: '', data: [36, 39, 42, 41, 43, 46, 44], points: { radius: 3 } },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme}>
                    <ValueLabels />
                </LineChart>
            </Stage>
        )
    },
}

export const NegativeValues: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'delta', label: 'Delta', color: '', data: [20, -15, 30, -25, 10, -5, 25], points: { radius: 3 } },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme}>
                    <ValueLabels />
                </LineChart>
            </Stage>
        )
    },
}

export const DualYAxes: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                color: '',
                data: [1200, 1500, 1100, 1800, 1600, 2100, 1900],
                yAxisId: 'left',
                points: { radius: 3 },
            },
            {
                key: 'conversion',
                label: 'Conversion %',
                color: '',
                data: [2.1, 2.5, 1.9, 3.2, 2.8, 3.6, 3.1],
                yAxisId: 'right',
                points: { radius: 3 },
            },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} tooltip={() => null}>
                    <ValueLabels valueFormatter={(v, si) => (si === 0 ? `$${v}` : `${v.toFixed(1)}%`)} />
                </LineChart>
            </Stage>
        )
    },
}

export const HiddenOnAuxiliarySeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const color = theme.colors[0]
        const base: Series = {
            key: 'visits',
            label: 'Visits',
            color,
            data: [20, 35, 28, 60, 45, 70, 52],
            points: { radius: 3 },
        }
        const trendline: Series = {
            key: 'visits__trendline',
            label: 'Visits',
            color,
            data: [22, 30, 38, 46, 54, 62, 70],
            stroke: { pattern: [1, 3] },
            overlay: true,
            visibility: { tooltip: false, valueLabel: false },
        }
        return (
            <Stage>
                <LineChart series={[base, trendline]} labels={LABELS} config={CONFIG} theme={theme}>
                    <ValueLabels />
                </LineChart>
            </Stage>
        )
    },
}

export const CrossSeriesOverlapRemoval: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const color = theme.colors[0]
        const series: Series[] = [
            { key: 'main', label: 'Main', color, data: [500, 480, 460, 450, 440, 430, 420], points: { radius: 3 } },
            {
                key: 'moving-avg',
                label: 'Moving avg',
                color,
                data: [490, 475, 463, 452, 443, 435, 428],
                stroke: { pattern: [10, 3] },
            },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme}>
                    <ValueLabels />
                </LineChart>
            </Stage>
        )
    },
}

export const WithCustomFormatter: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                color: '',
                data: [12000, 15500, 11000, 18400, 16200, 21100, 19800],
                points: { radius: 3 },
            },
        ]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme}>
                    <ValueLabels valueFormatter={(v) => `$${(v / 1000).toFixed(1)}k`} />
                </LineChart>
            </Stage>
        )
    },
}

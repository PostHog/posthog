import { Meta, StoryObj } from '@storybook/react'

import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart, ValueLabels } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const CONFIG: LineChartConfig = {
    showGrid: true,
    showCrosshair: false,
}

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 280, width: 480, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

const meta: Meta = {
    title: 'Components/HogCharts/ValueLabels',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const SingleSeries: Story = {
    render: () => {
        const theme = buildTheme()
        const series: Series[] = [
            {
                key: 'visits',
                label: 'Visits',
                color: 'var(--brand-blue)',
                data: [20, 35, 28, 60, 45, 70, 52],
                pointRadius: 3,
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

export const MultiSeriesCollision: Story = {
    render: () => {
        const theme = buildTheme()
        // Three dense series with values close enough in places that collision
        // avoidance should visibly drop some labels.
        const series: Series[] = [
            {
                key: 'desktop',
                label: 'Desktop',
                color: 'var(--brand-blue)',
                data: [40, 42, 44, 43, 45, 47, 46],
                pointRadius: 3,
            },
            {
                key: 'mobile',
                label: 'Mobile',
                color: 'var(--brand-red)',
                data: [38, 41, 40, 44, 46, 48, 47],
                pointRadius: 3,
            },
            {
                key: 'tablet',
                label: 'Tablet',
                color: 'var(--brand-yellow)',
                data: [36, 39, 42, 41, 43, 46, 44],
                pointRadius: 3,
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

export const NegativeValues: Story = {
    render: () => {
        const theme = buildTheme()
        const series: Series[] = [
            {
                key: 'delta',
                label: 'Delta',
                color: 'var(--brand-blue)',
                data: [20, -15, 30, -25, 10, -5, 25],
                pointRadius: 3,
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

export const DualYAxes: Story = {
    render: () => {
        const theme = buildTheme()
        const series: Series[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                color: 'var(--brand-blue)',
                data: [1200, 1500, 1100, 1800, 1600, 2100, 1900],
                yAxisId: 'left',
                pointRadius: 3,
            },
            {
                key: 'conversion',
                label: 'Conversion %',
                color: 'var(--brand-red)',
                data: [2.1, 2.5, 1.9, 3.2, 2.8, 3.6, 3.1],
                yAxisId: 'right',
                pointRadius: 3,
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

export const WithCustomFormatter: Story = {
    render: () => {
        const theme = buildTheme()
        const series: Series[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                color: 'var(--brand-blue)',
                data: [12000, 15500, 11000, 18400, 16200, 21100, 19800],
                pointRadius: 3,
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

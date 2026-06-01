import { Meta, StoryObj } from '@storybook/react'

import { BarChart, ReferenceLine, ValueLabels } from 'lib/hog-charts'
import type { BarChartConfig, Series } from 'lib/hog-charts'

import { Stage, useReactiveTheme } from '../story-helpers'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const TWO_SERIES: Series[] = [
    { key: 'desktop', label: 'Desktop', color: '', data: [40, 42, 44, 43, 45, 47, 46] },
    { key: 'mobile', label: 'Mobile', color: '', data: [38, 41, 40, 44, 46, 48, 47] },
]

const THREE_SERIES: Series[] = [
    ...TWO_SERIES,
    { key: 'tablet', label: 'Tablet', color: '', data: [12, 14, 11, 16, 18, 20, 19] },
]

const meta: Meta = { title: 'Components/HogCharts/BarChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const StackedDefault: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const Grouped: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const Percent: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'percent', showGrid: true }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const Horizontal: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true, axisOrientation: 'horizontal' }
        return (
            <Stage height={320}>
                <BarChart series={THREE_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const HorizontalGrouped: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true, axisOrientation: 'horizontal' }
        return (
            <Stage height={320}>
                <BarChart series={THREE_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const SingleSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [{ key: 'visits', label: 'Visits', color: '', data: [20, 35, 28, 60, 45, 70, 52] }]
        return (
            <Stage>
                <BarChart series={series} labels={DAYS} theme={theme} />
            </Stage>
        )
    },
}

export const WithValueLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        return (
            <Stage>
                <BarChart series={TWO_SERIES} labels={DAYS} config={config} theme={theme}>
                    <ValueLabels />
                </BarChart>
            </Stage>
        )
    },
}

export const WithReferenceLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        return (
            <Stage>
                <BarChart series={TWO_SERIES} labels={DAYS} config={config} theme={theme}>
                    <ReferenceLine value={80} label="Target" variant="goal" />
                </BarChart>
            </Stage>
        )
    },
}

export const NoGrid: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'stacked' }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const IncompletePeriod: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        const series: Series[] = THREE_SERIES.map((s) => ({ ...s, stroke: { partial: { fromIndex: 5 } } }))
        return (
            <Stage>
                <BarChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const HiddenSeries: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        const series: Series[] = THREE_SERIES.map((s, i) => ({
            ...s,
            visibility: i === 1 ? { excluded: true } : undefined,
        }))
        return (
            <Stage>
                <BarChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const NegativeValues: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        const series: Series[] = [{ key: 'delta', label: 'Delta', color: '', data: [20, -15, 30, -25, 10, -5, 25] }]
        return (
            <Stage>
                <BarChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

/** Stacked bars with a mix of positive and negative values per index. The d3 stack splits
 *  positive and negative contributions either side of the baseline, so the topmost positive
 *  series and bottommost negative series both round their cap. */
export const StackedMixedSign: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'inflow', label: 'Inflow', color: '', data: [12, 18, 9, 22, 14, 20, 16] },
            { key: 'refunds', label: 'Refunds', color: '', data: [-4, -7, -3, -10, -6, -8, -5] },
            { key: 'chargebacks', label: 'Chargebacks', color: '', data: [-1, -2, -1, -3, 0, -1, -2] },
        ]
        const config: BarChartConfig = { showGrid: true, barLayout: 'stacked' }
        return (
            <Stage>
                <BarChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const LargeDataset: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        const labels = Array.from({ length: 30 }, (_, i) => `Day ${i + 1}`)
        const series: Series[] = [
            { key: 'a', label: 'A', color: '', data: labels.map((_, i) => 20 + Math.round(15 * Math.sin(i / 3))) },
            { key: 'b', label: 'B', color: '', data: labels.map((_, i) => 12 + Math.round(8 * Math.cos(i / 4))) },
        ]
        return (
            <Stage>
                <BarChart series={series} labels={labels} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const CustomCornerRadius: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true, barCornerRadius: 12 }
        return (
            <Stage>
                <BarChart series={TWO_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

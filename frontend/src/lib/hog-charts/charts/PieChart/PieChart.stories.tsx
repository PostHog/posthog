import { Meta, StoryObj } from '@storybook/react'

import { Stage, useReactiveTheme } from '../../story-helpers'
import { PieChart, type PieChartConfig, type PieSlice } from './PieChart'

const THREE_SLICES: PieSlice[] = [
    { key: 'desktop', label: 'Desktop', value: 540 },
    { key: 'mobile', label: 'Mobile', value: 380 },
    { key: 'tablet', label: 'Tablet', value: 120 },
]

const SIX_SLICES: PieSlice[] = [
    { key: 'chrome', label: 'Chrome', value: 620 },
    { key: 'safari', label: 'Safari', value: 310 },
    { key: 'firefox', label: 'Firefox', value: 140 },
    { key: 'edge', label: 'Edge', value: 90 },
    { key: 'opera', label: 'Opera', value: 28 },
    { key: 'other', label: 'Other', value: 12 },
]

const meta: Meta = { title: 'Components/HogCharts/PieChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const Default: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <PieChart slices={THREE_SLICES} theme={theme} />
            </Stage>
        )
    },
}

export const Donut: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { innerRadius: 0.55 }
        return (
            <Stage>
                <PieChart slices={THREE_SLICES} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const ManySlices: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <PieChart slices={SIX_SLICES} theme={theme} />
            </Stage>
        )
    },
}

export const WithSliceLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { showLabelsOnSlices: true, showValuesOnSlices: false }
        return (
            <Stage>
                <PieChart slices={THREE_SLICES} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const WithSlicePadding: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { slicePadding: 0.02, innerRadius: 0.4 }
        return (
            <Stage>
                <PieChart slices={SIX_SLICES} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const HiddenValueLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { showValuesOnSlices: false }
        return (
            <Stage>
                <PieChart slices={SIX_SLICES} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const CustomValueFormatter: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { valueFormatter: (v) => `$${v.toLocaleString()}` }
        const slices: PieSlice[] = [
            { key: 'pro', label: 'Pro', value: 12400 },
            { key: 'team', label: 'Team', value: 6200 },
            { key: 'free', label: 'Free', value: 1800 },
        ]
        return (
            <Stage>
                <PieChart slices={slices} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const SingleSlice: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const slices: PieSlice[] = [{ key: 'only', label: 'All traffic', value: 100 }]
        return (
            <Stage>
                <PieChart slices={slices} theme={theme} />
            </Stage>
        )
    },
}

export const EmptyState: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <PieChart slices={[]} theme={theme} />
            </Stage>
        )
    },
}

export const SkewedDistribution: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const slices: PieSlice[] = [
            { key: 'big', label: 'Big', value: 980 },
            { key: 'medium', label: 'Medium', value: 60 },
            { key: 'small', label: 'Small', value: 14 },
            { key: 'tiny', label: 'Tiny', value: 3 },
        ]
        return (
            <Stage>
                <PieChart slices={slices} theme={theme} />
            </Stage>
        )
    },
}

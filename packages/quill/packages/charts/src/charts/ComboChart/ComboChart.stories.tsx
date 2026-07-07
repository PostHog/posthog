import { Meta, StoryObj } from '@storybook/react'

import type { ComboChartConfig, Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { ComboChart } from './ComboChart'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const meta: Meta = { title: 'Components/HogCharts/ComboChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const BarAndLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'visits', label: 'Visits', color: '', data: [40, 42, 44, 43, 45, 47, 46], type: 'bar' },
            { key: 'rolling', label: 'Rolling avg', color: '', data: [38, 40, 42, 43, 44, 45, 46], type: 'line' },
        ]
        const config: ComboChartConfig = { showGrid: true }
        return (
            <Stage>
                <ComboChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const AreaAndLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'visits', label: 'Visits', color: '', data: [40, 42, 44, 43, 45, 47, 46], type: 'area' },
            { key: 'rolling', label: 'Rolling avg', color: '', data: [38, 40, 42, 43, 44, 45, 46], type: 'line' },
        ]
        const config: ComboChartConfig = { showGrid: true }
        return (
            <Stage>
                <ComboChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const StackedBarsAndLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'desktop', label: 'Desktop', color: '', data: [22, 24, 28, 26, 30, 32, 31], type: 'bar' },
            { key: 'mobile', label: 'Mobile', color: '', data: [18, 18, 16, 17, 15, 15, 15], type: 'bar' },
            { key: 'total', label: 'Total (rolling)', color: '', data: [38, 40, 42, 43, 45, 47, 46], type: 'line' },
        ]
        const config: ComboChartConfig = { showGrid: true, barLayout: 'stacked' }
        return (
            <Stage>
                <ComboChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const GroupedBarsAndLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'a', label: 'A', color: '', data: [22, 24, 28, 26, 30, 32, 31], type: 'bar' },
            { key: 'b', label: 'B', color: '', data: [18, 18, 16, 17, 15, 15, 15], type: 'bar' },
            { key: 'avg', label: 'Avg', color: '', data: [20, 21, 22, 21, 22, 23, 23], type: 'line' },
        ]
        const config: ComboChartConfig = { showGrid: true, barLayout: 'grouped' }
        return (
            <Stage>
                <ComboChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

/** Bar on the left axis, line on the right — independent y-axes. */
export const DualYAxisBarAndLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                color: '',
                data: [1100, 1300, 1250, 1700, 1500, 1900, 1800],
                type: 'bar',
            },
            {
                key: 'conversion',
                label: 'Conversion',
                color: '',
                data: [0.022, 0.028, 0.025, 0.034, 0.031, 0.038, 0.036],
                type: 'line',
                yAxisId: 'right',
            },
        ]
        const config: ComboChartConfig = { showGrid: true }
        return (
            <Stage>
                <ComboChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

/** Line series declared before an area series in the input — covers the two-pass z-order: the
 *  area fill must paint behind the line regardless of series order. */
export const LineBeforeArea: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'line', label: 'Trend', color: '', data: [10, 14, 12, 22, 18, 26, 20], type: 'line' },
            { key: 'area', label: 'Range', color: '', data: [16, 20, 18, 28, 24, 32, 26], type: 'area' },
        ]
        const config: ComboChartConfig = { showGrid: true }
        return (
            <Stage>
                <ComboChart series={series} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const Empty: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <ComboChart series={[]} labels={[]} theme={theme} />
            </Stage>
        )
    },
}

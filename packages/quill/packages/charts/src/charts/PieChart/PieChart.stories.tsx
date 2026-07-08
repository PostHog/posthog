import { Meta, StoryObj } from '@storybook/react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { PieChart } from './PieChart'
import type { PieChartConfig } from './PieChart'

const BROWSERS: Series[] = [
    { key: 'chrome', label: 'Chrome', color: '', data: [4200] },
    { key: 'safari', label: 'Safari', color: '', data: [1800] },
    { key: 'firefox', label: 'Firefox', color: '', data: [620] },
    { key: 'edge', label: 'Edge', color: '', data: [410] },
    { key: 'other', label: 'Other', color: '', data: [80] },
]

const ONE_BIG_TWO_TINY: Series[] = [
    { key: 'dominant', label: 'Direct', color: '', data: [9500] },
    { key: 'small-1', label: 'Search', color: '', data: [80] },
    { key: 'small-2', label: 'Social', color: '', data: [60] },
]

const meta: Meta = { title: 'Components/HogCharts/PieChart', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

export const PieDefault: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <PieChart series={BROWSERS} theme={theme} />
            </Stage>
        )
    },
}

export const Donut: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { innerRadiusRatio: 0.55 }
        const total = BROWSERS.reduce((acc, s) => acc + s.data[0], 0)
        return (
            <Stage>
                <PieChart
                    series={BROWSERS}
                    theme={theme}
                    config={config}
                    centerLabel={
                        <div>
                            <div style={{ fontSize: 12, opacity: 0.7 }}>Sessions</div>
                            <div style={{ fontSize: 22, fontWeight: 700 }}>{total.toLocaleString()}</div>
                        </div>
                    }
                />
            </Stage>
        )
    },
}

export const Percent: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { isPercent: true }
        return (
            <Stage>
                <PieChart series={BROWSERS} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const SingleSlice: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [{ key: 'only', label: 'All events', color: '', data: [12345] }]
        return (
            <Stage>
                <PieChart series={series} theme={theme} />
            </Stage>
        )
    },
}

export const WithBreakdownLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { showLabelOnSlice: true, showValueOnSlice: true }
        return (
            <Stage>
                <PieChart series={BROWSERS} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const LabelsTowardRim: Story = {
    render: () => {
        const theme = useReactiveTheme()
        // Push labels out onto the wider part of each wedge and skip slices under 10%, so a long
        // tail of thin slices doesn't crowd labels at the center.
        const config: PieChartConfig = {
            showLabelOnSlice: true,
            showValueOnSlice: false,
            labelRadiusRatio: 0.72,
            minSlicePercentForLabel: 0.1,
        }
        return (
            <Stage>
                <PieChart series={BROWSERS} theme={theme} config={config} />
            </Stage>
        )
    },
}

export const LongLabelTooltip: Story = {
    render: () => {
        const theme = useReactiveTheme()
        // Slices below 5% are hidden from on-slice labels — but the tooltip should still show
        // their full label on hover, even when the breakdown text is long.
        return (
            <Stage>
                <PieChart series={ONE_BIG_TWO_TINY} theme={theme} />
            </Stage>
        )
    },
}

export const NoHoverOffset: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: PieChartConfig = { disableHoverOffset: true }
        return (
            <Stage>
                <PieChart series={BROWSERS} theme={theme} config={config} />
            </Stage>
        )
    },
}

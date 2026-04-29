import { Meta, StoryObj } from '@storybook/react'

import { buildTheme } from 'lib/charts/utils/theme'
import { BarChart, ReferenceLine, ValueLabels } from 'lib/hog-charts'
import type { BarChartConfig, Series } from 'lib/hog-charts'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const TWO_SERIES: Series[] = [
    {
        key: 'desktop',
        label: 'Desktop',
        color: 'var(--brand-blue)',
        data: [40, 42, 44, 43, 45, 47, 46],
    },
    {
        key: 'mobile',
        label: 'Mobile',
        color: 'var(--brand-red)',
        data: [38, 41, 40, 44, 46, 48, 47],
    },
]

const THREE_SERIES: Series[] = [
    ...TWO_SERIES,
    {
        key: 'tablet',
        label: 'Tablet',
        color: 'var(--brand-yellow)',
        data: [12, 14, 11, 16, 18, 20, 19],
    },
]

function Stage({ children, height = 280 }: { children: React.ReactNode; height?: number }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height, width: 480, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

const meta: Meta = {
    title: 'Components/HogCharts/BarChart',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const StackedDefault: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const Grouped: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const Percent: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'percent', showGrid: true }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const Horizontal: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true, axisOrientation: 'horizontal' }
        return (
            <Stage height={320}>
                <BarChart series={THREE_SERIES} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const HorizontalGrouped: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true, axisOrientation: 'horizontal' }
        return (
            <Stage height={320}>
                <BarChart series={THREE_SERIES} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const SingleSeries: Story = {
    render: () => {
        const theme = buildTheme()
        const series: Series[] = [
            {
                key: 'visits',
                label: 'Visits',
                color: 'var(--brand-blue)',
                data: [20, 35, 28, 60, 45, 70, 52],
            },
        ]
        return (
            <Stage>
                <BarChart series={series} labels={LABELS} theme={theme} />
            </Stage>
        )
    },
}

export const WithValueLabels: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        return (
            <Stage>
                <BarChart series={TWO_SERIES} labels={LABELS} config={config} theme={theme}>
                    <ValueLabels />
                </BarChart>
            </Stage>
        )
    },
}

export const WithReferenceLine: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        return (
            <Stage>
                <BarChart series={TWO_SERIES} labels={LABELS} config={config} theme={theme}>
                    <ReferenceLine value={80} label="Target" variant="goal" />
                </BarChart>
            </Stage>
        )
    },
}

export const NoGrid: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'stacked' }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const IncompletePeriod: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        const series: Series[] = THREE_SERIES.map((s) => ({
            ...s,
            stroke: { partial: { fromIndex: 5 } },
        }))
        return (
            <Stage>
                <BarChart series={series} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const HiddenSeries: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        const series: Series[] = THREE_SERIES.map((s, i) => ({
            ...s,
            visibility: i === 1 ? { excluded: true } : undefined,
        }))
        return (
            <Stage>
                <BarChart series={series} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const NegativeValues: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true }
        const series: Series[] = [
            {
                key: 'delta',
                label: 'Delta',
                color: 'var(--brand-blue)',
                data: [20, -15, 30, -25, 10, -5, 25],
            },
        ]
        return (
            <Stage>
                <BarChart series={series} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const StackedWithNegatives: Story = {
    // Stacked layout uses d3.stack with the default offset, which clamps negative values to 0
    // (see buildStackData in scales.ts) — so this story documents that negative values disappear
    // from the stack rather than being charted below the baseline. Use grouped layout for
    // signed-value comparisons.
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        const series: Series[] = [
            {
                key: 'inflow',
                label: 'Inflow',
                color: 'var(--brand-blue)',
                data: [40, 50, 30, 60, 45, 55, 50],
            },
            {
                key: 'outflow',
                label: 'Outflow (negative — clamped to 0 in stacked layout)',
                color: 'var(--brand-red)',
                data: [-20, -25, -10, -35, 15, -15, -20],
            },
        ]
        return (
            <Stage>
                <BarChart series={series} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const LargeDataset: Story = {
    render: () => {
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true }
        const labels = Array.from({ length: 30 }, (_, i) => `Day ${i + 1}`)
        const series: Series[] = [
            {
                key: 'a',
                label: 'A',
                color: 'var(--brand-blue)',
                data: labels.map((_, i) => 20 + Math.round(15 * Math.sin(i / 3))),
            },
            {
                key: 'b',
                label: 'B',
                color: 'var(--brand-red)',
                data: labels.map((_, i) => 12 + Math.round(8 * Math.cos(i / 4))),
            },
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
        const theme = buildTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true, barCornerRadius: 12 }
        return (
            <Stage>
                <BarChart series={TWO_SERIES} labels={LABELS} config={config} theme={theme} />
            </Stage>
        )
    },
}

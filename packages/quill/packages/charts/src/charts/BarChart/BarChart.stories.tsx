import { Meta, StoryObj } from '@storybook/react'

import type { BarChartConfig, BarFillStyle, Series } from '../../core/types'
import { ReferenceLine } from '../../overlays/ReferenceLine'
import { ValueLabels } from '../../overlays/ValueLabels'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { BarChart } from './BarChart'

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

export const WithBarTrack: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'grouped', showGrid: true, barCornerRadius: 6, bars: { track: true } }
        return (
            <Stage>
                <BarChart series={THREE_SERIES} labels={DAYS} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const WithBarTrackCeiling: Story = {
    render: () => {
        const theme = useReactiveTheme()
        // Per-bar `trackData` caps each track at a ceiling (funnel compare's entry level): the "previous"
        // series fills its track only up to 70, leaving the region above blank — the volume gap — instead
        // of drawing it as drop-off. "Current" has no ceiling, so its track spans the full axis.
        const series: Series[] = [
            { key: 'current', label: 'Current', color: '', data: [100, 60, 40] },
            { key: 'previous', label: 'Previous', color: '', data: [70, 45, 30], trackData: [70, 70, 70] },
        ]
        const config: BarChartConfig = {
            barLayout: 'grouped',
            showGrid: true,
            barCornerRadius: 6,
            bars: { track: true, valueDomain: [0, 100] },
        }
        return (
            <Stage>
                <BarChart series={series} labels={['Step 1', 'Step 2', 'Step 3']} config={config} theme={theme} />
            </Stage>
        )
    },
}

export const StackedWithTrackCeiling: Story = {
    render: () => {
        const theme = useReactiveTheme()
        // Stacked counterpart of WithBarTrackCeiling — the shape of a top-to-bottom funnel compare bar.
        // The stack (converted + drop-off) sums to the period's entry level (70), and `trackData` on the
        // drop-off declares that ceiling: the region beyond it is fully inert (no tooltip, pointer
        // cursor, or highlight when hovered), with no track drawn.
        const series: Series[] = [
            { key: 'converted', label: 'Converted', color: '', data: [45] },
            { key: 'drop-off', label: 'Drop-off', color: '', data: [25], trackData: [70] },
        ]
        const config: BarChartConfig = {
            barLayout: 'stacked',
            axisOrientation: 'horizontal',
            showGrid: true,
            barCornerRadius: 6,
            bars: { valueDomain: [0, 100] },
        }
        return (
            <Stage height={120}>
                <BarChart series={series} labels={['Step 1']} config={config} theme={theme} />
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

export const HorizontalAggregatedSingle: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = { barLayout: 'stacked', showGrid: true, axisOrientation: 'horizontal' }
        const series: Series[] = [{ key: 'all', label: 'All events', color: '', data: [103000] }]
        return (
            <Stage height={320}>
                <BarChart series={series} labels={['All events']} config={config} theme={theme} />
            </Stage>
        )
    },
}

// Exercises the horizontal value-tick de-overlap: wide thousands-separated labels (millions) in a
// compact panel, where consecutive ticks genuinely collide. The de-overlap pass hides the colliding
// ones so the axis reads cleanly instead of smearing into "0 500,0001,000,000…" — gridlines stay at
// every tick, labels only at the survivors. Remove the pass and the labels overlap again; the exact
// gap that decides which survive is pinned by AxisLabels.test.ts.
export const HorizontalWideValueLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config: BarChartConfig = {
            axisOrientation: 'horizontal',
            showGrid: true,
            yTickFormatter: (v) => v.toLocaleString('en-US'),
            barCornerRadius: 4,
            bars: { fitToHeight: true },
        }
        const labels = ['/pricing', '/signup', '/product', '/docs', '/blog']
        const series: Series[] = [
            { key: 'views', label: 'Views', color: '', data: [2_300_000, 1_510_000, 940_000, 460_000, 180_000] },
        ]
        return (
            <Stage width={340} height={280}>
                <BarChart series={series} labels={labels} config={config} theme={theme} />
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

const BREAKDOWN_LABELS = ['/login', 'Other', '/projects', '/surveys', '/dashboard', '/insights', '/persons', '/events']
const BREAKDOWN_DATA = [9200, 8400, 6100, 5200, 4300, 3600, 2800, 2100]

function FillStyleColumn({ title, fillStyle }: { title: string; fillStyle: BarFillStyle }): JSX.Element {
    const theme = useReactiveTheme()
    // One series with a value per category — per-bar colors echo a breakdown chart.
    const series: Series[] = [
        {
            key: 'pages',
            label: 'Pageviews',
            color: theme.colors[0],
            data: BREAKDOWN_DATA,
            bars: BREAKDOWN_DATA.map((_, i) => ({ color: theme.colors[i % theme.colors.length] })),
        },
    ]
    const config: BarChartConfig = {
        barLayout: 'grouped',
        showGrid: true,
        axisOrientation: 'horizontal',
        barCornerRadius: 4,
        bars: { fillStyle },
    }
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <span className="text-xs font-semibold text-muted-foreground">{title}</span>
            <Stage width={340} height={360}>
                <BarChart series={series} labels={BREAKDOWN_LABELS} config={config} theme={theme} />
            </Stage>
        </div>
    )
}

export const FillStyles: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', gap: 24, alignItems: 'flex-start' }}>
            <FillStyleColumn title="flat (current)" fillStyle="flat" />
            <FillStyleColumn title="gradient" fillStyle="gradient" />
            <FillStyleColumn title="gloss" fillStyle="gloss" />
        </div>
    ),
}

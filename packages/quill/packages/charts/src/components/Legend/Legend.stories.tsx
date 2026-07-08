import { Meta, StoryObj } from '@storybook/react'
import { useMemo, useState, type ReactNode } from 'react'

import { DAYS, SERIES } from '../../charts/time-series-fixtures'
import { TimeSeriesBarChart } from '../../charts/TimeSeriesBarChart/TimeSeriesBarChart'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { ChartLegend } from './ChartLegend'
import { Legend, type LegendItem } from './Legend'
import { legendItemsFromSeries } from './legendItemsFromSeries'

const LIFECYCLE: LegendItem[] = [
    { key: 'new', label: 'New', color: '#22c55e' },
    { key: 'returning', label: 'Returning', color: '#3b82f6' },
    { key: 'resurrecting', label: 'Resurrecting', color: '#a855f7' },
    { key: 'dormant', label: 'Dormant', color: '#f97316' },
]

const MANY: LegendItem[] = Array.from({ length: 12 }, (_, i) => ({
    key: `series-${i}`,
    label: `Breakdown value ${i + 1} with a fairly long name`,
    color: `hsl(${(i * 36) % 360} 70% 55%)`,
}))

const meta: Meta = {
    title: 'Components/HogCharts/Legend',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj

export const Horizontal: Story = {
    render: () => (
        <div className="w-[480px]">
            <Legend items={LIFECYCLE} />
        </div>
    ),
}

export const Vertical: Story = {
    render: () => (
        <div className="w-[200px]">
            <Legend items={LIFECYCLE} orientation="vertical" align="start" />
        </div>
    ),
}

export const Interactive: Story = {
    render: () => {
        function InteractiveLegend(): JSX.Element {
            const [hidden, setHidden] = useState<string[]>([])
            const toggle = (key: string): void =>
                setHidden((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]))
            return (
                <div className="w-[480px]">
                    <Legend items={LIFECYCLE} hiddenKeys={hidden} onItemClick={toggle} />
                </div>
            )
        }
        return <InteractiveLegend />
    },
}

export const ManyItemsWraps: Story = {
    render: () => (
        <div className="w-[480px] border border-border rounded p-2">
            <Legend items={MANY} />
        </div>
    ),
}

const LONG_LABELS: LegendItem[] = [
    { key: 'a', label: 'pageview · Chrome · United States · organic search', color: '#22c55e' },
    { key: 'b', label: 'pageview · Safari · United Kingdom · paid social', color: '#3b82f6' },
    { key: 'c', label: 'Short one', color: '#f97316' },
]

const LONG_SINGLE: LegendItem[] = [
    { key: 'a', label: 'pageview · Chrome · United States · organic search · returning visitor', color: '#22c55e' },
]

// Clipping is driven purely by available space, so the same labels show unclipped when they fit and
// ellipsize only when their row can't. Top-to-bottom: a lone long series in a wide box (fits, no clip),
// the same series in a narrow box (clips), a horizontal group that wraps before shrinking any row, and a
// vertical legend that truncates at its column edge. The full text is always on the row's `title` tooltip.
export const LongLabelsTruncate: Story = {
    render: () => (
        <div className="flex flex-col gap-4">
            <div className="w-[640px] border border-border rounded p-2">
                <Legend items={LONG_SINGLE} align="start" />
            </div>
            <div className="w-[240px] border border-border rounded p-2">
                <Legend items={LONG_SINGLE} align="start" />
            </div>
            <div className="w-[480px] border border-border rounded p-2">
                <Legend items={LONG_LABELS} />
            </div>
            <div className="w-[200px] border border-border rounded p-2">
                <Legend items={LONG_LABELS} orientation="vertical" align="start" />
            </div>
        </div>
    ),
}

function ChartLegendStory({
    show = true,
    position,
}: {
    show?: boolean
    position: 'top' | 'bottom' | 'left' | 'right'
}): JSX.Element {
    const theme = useReactiveTheme()
    const items = useMemo(() => legendItemsFromSeries(SERIES, theme), [theme])
    return (
        <Stage width={520} height={320}>
            <ChartLegend show={show} items={items} position={position}>
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ yAxis: { showGrid: true } }}
                />
            </ChartLegend>
        </Stage>
    )
}

export const LayoutTop: Story = {
    render: () => <ChartLegendStory position="top" />,
}
export const LayoutBottom: Story = {
    render: () => <ChartLegendStory position="bottom" />,
}
export const LayoutLeft: Story = {
    render: () => <ChartLegendStory position="left" />,
}
export const LayoutRight: Story = {
    render: () => <ChartLegendStory position="right" />,
}
export const LegendHidden: Story = {
    render: () => <ChartLegendStory show={false} position="top" />,
}

// The chart owns the toggle state — `config.legend` is all that's needed; clicking a row hides
// that series (dimmed in the legend) and the axes rescale into the freed space. These stories
// snapshot the built-in legend at each position around the chart, not the legend in isolation.
function BuiltInToggleStory({
    position,
    renderItem,
}: {
    position: 'top' | 'bottom' | 'left' | 'right'
    renderItem?: (node: ReactNode, item: LegendItem) => ReactNode
}): JSX.Element {
    const theme = useReactiveTheme()
    return (
        <Stage width={520} height={320}>
            <TimeSeriesBarChart
                series={SERIES}
                labels={DAYS}
                theme={theme}
                config={{
                    yAxis: { showGrid: true },
                    legend: { show: true, position, renderItem },
                }}
            />
        </Stage>
    )
}

export const BuiltInToggleTop: Story = { render: () => <BuiltInToggleStory position="top" /> }
export const BuiltInToggleBottom: Story = { render: () => <BuiltInToggleStory position="bottom" /> }
export const BuiltInToggleLeft: Story = { render: () => <BuiltInToggleStory position="left" /> }
export const BuiltInToggleRight: Story = { render: () => <BuiltInToggleStory position="right" /> }

// `renderItem` wraps each row so a consumer can augment it (here a native-title tooltip standing in
// for a right-click context menu) while keeping the default swatch/label/toggle rendering.
export const BuiltInToggleRenderItem: Story = {
    render: () => (
        <BuiltInToggleStory
            position="bottom"
            renderItem={(node, item) => <span title={`Right-click ${item.label} for options`}>{node}</span>}
        />
    ),
}

import { Meta, StoryObj } from '@storybook/react'
import { useMemo, useState } from 'react'

import { DAYS, SERIES } from '../../charts/time-series-fixtures'
import { TimeSeriesBarChart } from '../../charts/TimeSeriesBarChart/TimeSeriesBarChart'
import { Stage, useReactiveTheme } from '../../story-helpers'
import { ChartLegendLayout } from './ChartLegendLayout'
import { Legend, type LegendItem } from './Legend'
import { legendItemsFromSeries } from './legendItemsFromSeries'

const LIFECYCLE_ITEMS: LegendItem[] = [
    { key: 'new', label: 'New', color: '#22c55e' },
    { key: 'returning', label: 'Returning', color: '#3b82f6' },
    { key: 'resurrecting', label: 'Resurrecting', color: '#a855f7' },
    { key: 'dormant', label: 'Dormant', color: '#f97316' },
]

const MANY_ITEMS: LegendItem[] = Array.from({ length: 12 }, (_, i) => ({
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
            <Legend items={LIFECYCLE_ITEMS} />
        </div>
    ),
}

export const Vertical: Story = {
    render: () => (
        <div className="w-[200px]">
            <Legend items={LIFECYCLE_ITEMS} orientation="vertical" align="start" />
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
                <div className="flex flex-col gap-2 w-[480px]">
                    <Legend items={LIFECYCLE_ITEMS} hiddenKeys={hidden} onItemClick={toggle} />
                    <span className="text-xs text-muted">Click an item to toggle its dimmed state.</span>
                </div>
            )
        }
        return <InteractiveLegend />
    },
}

export const ManyItemsWraps: Story = {
    render: () => (
        <div className="w-[480px] border border-border rounded p-2">
            <Legend items={MANY_ITEMS} />
        </div>
    ),
}

function ChartWithLegend({ position }: { position: 'top' | 'bottom' | 'left' | 'right' }): JSX.Element {
    const theme = useReactiveTheme()
    const isHorizontal = position === 'left' || position === 'right'
    const items = useMemo(() => legendItemsFromSeries(SERIES, theme), [theme])
    const legend = <Legend items={items} orientation={isHorizontal ? 'vertical' : 'horizontal'} />
    return (
        <Stage width={520} height={320}>
            <ChartLegendLayout legend={legend} position={position}>
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ yAxis: { showGrid: true } }}
                />
            </ChartLegendLayout>
        </Stage>
    )
}

export const LayoutTop: Story = { render: () => <ChartWithLegend position="top" /> }
export const LayoutBottom: Story = { render: () => <ChartWithLegend position="bottom" /> }
export const LayoutLeft: Story = { render: () => <ChartWithLegend position="left" /> }
export const LayoutRight: Story = { render: () => <ChartWithLegend position="right" /> }

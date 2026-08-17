import { Meta, StoryObj } from '@storybook/react'

import { LineChart } from '../charts/LineChart/LineChart'
import type { LineChartConfig, Series, TooltipContext } from '../core/types'
import { playHoverAtFraction, Stage, useReactiveTheme } from '../story-helpers'
import { DefaultTooltip } from './DefaultTooltip'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const CONFIG: LineChartConfig = { showGrid: true, showCrosshair: true }

interface ColumnMeta {
    /** Suffix appended to this column's values (e.g. a currency or unit). */
    unit: string
}

const meta: Meta = { title: 'Components/HogCharts/DefaultTooltip', parameters: { layout: 'centered' } }
export default meta

type Story = StoryObj<{}>

/** Per-series formatter + total row: each row formats with its own column's unit, and the footer
 *  sums the visible (non-overlay) series. */
export const PerSeriesFormatterWithTotal: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series<ColumnMeta>[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                color: '',
                data: [120, 180, 150, 240, 210, 300, 260],
                meta: { unit: '$' },
            },
            { key: 'refunds', label: 'Refunds', color: '', data: [12, 18, 9, 24, 15, 30, 21], meta: { unit: '$' } },
        ]
        const renderTooltip = (ctx: TooltipContext<ColumnMeta>): React.ReactNode => (
            <DefaultTooltip
                {...ctx}
                valueFormatter={(value, entry) => `${entry.series.meta?.unit ?? ''}${value.toLocaleString()}`}
                showTotal
                totalFormatter={(value) => `$${value.toLocaleString()}`}
            />
        )
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <Stage>
                    <LineChart<ColumnMeta>
                        series={series}
                        labels={DAYS}
                        config={CONFIG}
                        theme={theme}
                        tooltip={renderTooltip}
                    />
                </Stage>
            </div>
        )
    },
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.5)
    },
}

/** A goal-line overlay series is excluded from the total — only Revenue and Refunds are summed. */
export const TotalExcludesOverlay: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series<ColumnMeta>[] = [
            {
                key: 'revenue',
                label: 'Revenue',
                color: '',
                data: [120, 180, 150, 240, 210, 300, 260],
                meta: { unit: '$' },
            },
            { key: 'refunds', label: 'Refunds', color: '', data: [12, 18, 9, 24, 15, 30, 21], meta: { unit: '$' } },
            {
                key: 'goal',
                label: 'Goal',
                color: '',
                data: [200, 200, 200, 200, 200, 200, 200],
                overlay: true,
                stroke: { pattern: [6, 6] },
                meta: { unit: '$' },
            },
        ]
        const renderTooltip = (ctx: TooltipContext<ColumnMeta>): React.ReactNode => (
            <DefaultTooltip
                {...ctx}
                valueFormatter={(value, entry) => `${entry.series.meta?.unit ?? ''}${value.toLocaleString()}`}
                showTotal
                totalFormatter={(value) => `$${value.toLocaleString()}`}
            />
        )
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <Stage>
                    <LineChart<ColumnMeta>
                        series={series}
                        labels={DAYS}
                        config={CONFIG}
                        theme={theme}
                        tooltip={renderTooltip}
                    />
                </Stage>
            </div>
        )
    },
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.5)
    },
}

/** `rowComparator` keeps each metric's two periods adjacent. Sorted by value the rows would
 *  interleave (Revenue then, Revenue now, Refunds then, Refunds now), so the pairs a reader wants
 *  to compare would sit apart. */
export const PairedRowOrder: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series<ColumnMeta>[] = [
            { key: 'revenue-now', label: 'Revenue', color: '', data: [120, 180, 150, 240, 210, 300, 260] },
            { key: 'refunds-now', label: 'Refunds', color: '', data: [12, 18, 9, 24, 15, 30, 21] },
            { key: 'revenue-then', label: 'Revenue (previous)', color: '', data: [140, 200, 165, 260, 230, 320, 280] },
            { key: 'refunds-then', label: 'Refunds (previous)', color: '', data: [9, 14, 7, 19, 12, 25, 17] },
        ]
        // Rank by the current period's value, then keep the previous period directly below it.
        const order = ['revenue-now', 'revenue-then', 'refunds-now', 'refunds-then']
        const renderTooltip = (ctx: TooltipContext<ColumnMeta>): React.ReactNode => (
            <DefaultTooltip
                {...ctx}
                sortedByValue
                rowComparator={(a, b) => order.indexOf(a.series.key) - order.indexOf(b.series.key)}
            />
        )
        return (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
                <Stage>
                    <LineChart<ColumnMeta>
                        series={series}
                        labels={DAYS}
                        config={CONFIG}
                        theme={theme}
                        tooltip={renderTooltip}
                    />
                </Stage>
            </div>
        )
    },
    play: async ({ canvasElement }) => {
        await playHoverAtFraction(canvasElement, 0.5)
    },
}

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

import { Meta, StoryObj } from '@storybook/react'

import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { trendLine } from 'lib/statistics'

import { Stage, useReactiveTheme } from './story-helpers'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const CONFIG: LineChartConfig = {
    showGrid: true,
    showCrosshair: false,
}

function trendLineOverlay(parent: Series, fitUpTo?: number): Series {
    return {
        key: `${parent.key}__trendline`,
        label: parent.label,
        color: parent.color,
        yAxisId: parent.yAxisId,
        data: trendLine(parent.data, fitUpTo),
        stroke: { pattern: [1, 3] },
        visibility: { fromTooltip: true },
    }
}

const meta: Meta = {
    title: 'Components/HogCharts/TrendLines',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const WithTrendLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const base: Series = {
            key: 'visits',
            label: 'Visits',
            color: theme.colors[0],
            data: [20, 35, 28, 60, 45, 70, 52],
            points: { radius: 3 },
        }
        const series: Series[] = [base, trendLineOverlay(base)]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

export const MultiSeriesWithTrendLines: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const visits: Series = {
            key: 'visits',
            label: 'Visits',
            color: theme.colors[0],
            data: [40, 42, 44, 43, 55, 57, 66],
            points: { radius: 3 },
        }
        const signups: Series = {
            key: 'signups',
            label: 'Signups',
            color: theme.colors[1],
            data: [38, 36, 30, 32, 28, 22, 18],
            points: { radius: 3 },
        }
        const series: Series[] = [visits, signups, trendLineOverlay(visits), trendLineOverlay(signups)]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

export const TrendLineWithIncompletePeriod: Story = {
    render: () => {
        const theme = useReactiveTheme()
        // First 5 buckets show a steady climb (fit target); last 2 are artificially low
        // because the period is still in progress — they'd pull the slope down if included.
        const data = [20, 25, 35, 40, 50, 15, 8]
        const fromIndex = 5

        const base: Series = {
            key: 'visits',
            label: 'Visits',
            color: theme.colors[0],
            data,
            points: { radius: 3 },
            stroke: { partial: { fromIndex } },
        }
        const series: Series[] = [base, trendLineOverlay(base, fromIndex)]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

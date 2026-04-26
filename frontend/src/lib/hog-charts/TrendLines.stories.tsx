import { Meta, StoryObj } from '@storybook/react'

import { buildTheme } from 'lib/charts/utils/theme'
import { LineChart } from 'lib/hog-charts'
import type { LineChartConfig, Series } from 'lib/hog-charts'
import { trendLine } from 'lib/statistics'

const LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const CONFIG: LineChartConfig = {
    showGrid: true,
    showCrosshair: false,
}

function Stage({ children }: { children: React.ReactNode }): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ height: 280, width: 480, display: 'flex', flexDirection: 'column' }}>{children}</div>
    )
}

function trendLineOverlay(parent: Series, fitUpTo?: number): Series {
    return {
        key: `${parent.key}__trendline`,
        label: parent.label,
        color: parent.color,
        yAxisId: parent.yAxisId,
        data: trendLine(parent.data, fitUpTo),
        dashPattern: [1, 3],
        pointRadius: 0,
        hideFromTooltip: true,
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
        const theme = buildTheme()
        const base: Series = {
            key: 'visits',
            label: 'Visits',
            color: 'var(--brand-blue)',
            data: [20, 35, 28, 60, 45, 70, 52],
            pointRadius: 3,
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
        const theme = buildTheme()
        const visits: Series = {
            key: 'visits',
            label: 'Visits',
            color: 'var(--brand-blue)',
            data: [40, 42, 44, 43, 55, 57, 66],
            pointRadius: 3,
        }
        const signups: Series = {
            key: 'signups',
            label: 'Signups',
            color: 'var(--brand-red)',
            data: [38, 36, 30, 32, 28, 22, 18],
            pointRadius: 3,
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
        const theme = buildTheme()
        // First 5 buckets show a steady climb (fit target); last 2 are artificially low
        // because the period is still in progress — they'd pull the slope down if included.
        const data = [20, 25, 35, 40, 50, 15, 8]
        const dashedFromIndex = 5

        const base: Series = {
            key: 'visits',
            label: 'Visits',
            color: 'var(--brand-blue)',
            data,
            pointRadius: 3,
            dashedFromIndex,
        }
        const series: Series[] = [base, trendLineOverlay(base, dashedFromIndex)]
        return (
            <Stage>
                <LineChart series={series} labels={LABELS} config={CONFIG} theme={theme} />
            </Stage>
        )
    },
}

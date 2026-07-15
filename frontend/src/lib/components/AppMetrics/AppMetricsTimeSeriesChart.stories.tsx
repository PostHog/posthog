import { Meta, StoryObj } from '@storybook/react'
import { ReactNode } from 'react'

import { getColorVar } from 'lib/colors'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'
import { AppMetricsTimeSeriesChart } from './AppMetricsTimeSeriesChart'

const meta: Meta<typeof AppMetricsTimeSeriesChart> = {
    title: 'Components/AppMetricsTimeSeriesChart',
    component: AppMetricsTimeSeriesChart,
    parameters: {
        layout: 'centered',
        testOptions: { snapshotBrowsers: ['chromium'] },
    },
}
export default meta

type Story = StoryObj<typeof AppMetricsTimeSeriesChart>

function exampleTimeSeries(): AppMetricsTimeSeriesResponse {
    const labels = Array.from({ length: 14 }, (_, i) => `2025-06-${String(i + 1).padStart(2, '0')}`)
    return {
        labels,
        series: [
            { name: 'succeeded', values: labels.map((_, i) => Math.round(120 + 80 * Math.sin(i / 3))) },
            { name: 'failed', values: labels.map((_, i) => Math.max(0, Math.round(25 * Math.sin(i / 2) - 5))) },
            { name: 'filtered', values: labels.map((_, i) => 10 + (i % 4) * 3) },
        ],
    }
}

function Stage({ children, height = 320 }: { children: ReactNode; height?: number }): JSX.Element {
    // eslint-disable-next-line react/forbid-dom-props
    return <div style={{ width: 760, height }}>{children}</div>
}

export const Default: Story = {
    render: () => (
        <Stage>
            <AppMetricsTimeSeriesChart timeSeries={exampleTimeSeries()} />
        </Stage>
    ),
}

/** The AppMetricSummary tile shape: axes, ticks and grid hidden, single override color. */
export const Minimal: Story = {
    render: () => (
        <Stage height={160}>
            <AppMetricsTimeSeriesChart
                timeSeries={exampleTimeSeries()}
                seriesOverrides={{
                    succeeded: { color: getColorVar('success') },
                    failed: { color: getColorVar('success') },
                    filtered: { color: getColorVar('success') },
                }}
                minimal
            />
        </Stage>
    ),
}

/** Sub-day intervals: labels carry a time part, changing the x-axis ticks (and, on hover, the tooltip label format). */
export const HourlyLabels: Story = {
    render: () => (
        <Stage>
            <AppMetricsTimeSeriesChart
                timeSeries={{
                    labels: Array.from({ length: 24 }, (_, i) => `2025-06-01 ${String(i).padStart(2, '0')}:00`),
                    series: [
                        {
                            name: 'succeeded',
                            values: Array.from({ length: 24 }, (_, i) => Math.round(40 + 30 * Math.sin(i / 4))),
                        },
                    ],
                }}
            />
        </Stage>
    ),
}

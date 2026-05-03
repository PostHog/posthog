import { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesLineChart } from 'lib/hog-charts'
import type { Series, TimeInterval } from 'lib/hog-charts'

import { Stage, useReactiveTheme } from '../../story-helpers'

const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

const SERIES: Series[] = [
    { key: 'visits', label: 'Visits', data: [20, 35, 28, 60, 45, 70, 52] },
    { key: 'signups', label: 'Sign-ups', data: [4, 8, 6, 14, 11, 19, 13] },
    { key: 'activations', label: 'Activations', data: [2, 5, 4, 9, 7, 12, 8] },
]

const meta: Meta = {
    title: 'Components/HogCharts/TimeSeriesLineChart',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const Basic: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

const HOURLY_LABELS = Array.from({ length: 24 }, (_, i) => `2025-04-01 ${String(i).padStart(2, '0')}:00:00`)
const HOURLY_SERIES: Series[] = [
    {
        key: 'visits',
        label: 'Visits',
        data: [12, 9, 7, 6, 8, 14, 22, 35, 48, 55, 60, 64, 62, 58, 54, 50, 46, 44, 40, 36, 30, 24, 18, 14],
    },
]

const DAILY_LABELS = Array.from({ length: 30 }, (_, i) => {
    const d = new Date(Date.UTC(2025, 2, 15))
    d.setUTCDate(d.getUTCDate() + i)
    return d.toISOString().slice(0, 10)
})
const DAILY_SERIES: Series[] = [
    {
        key: 'visits',
        label: 'Visits',
        data: DAILY_LABELS.map((_, i) => 40 + Math.round(20 * Math.sin(i / 4))),
    },
]

const MONTHLY_LABELS = [
    '2024-09-01',
    '2024-10-01',
    '2024-11-01',
    '2024-12-01',
    '2025-01-01',
    '2025-02-01',
    '2025-03-01',
    '2025-04-01',
    '2025-05-01',
    '2025-06-01',
    '2025-07-01',
    '2025-08-01',
]
const MONTHLY_SERIES: Series[] = [
    { key: 'visits', label: 'Visits', data: [120, 135, 150, 142, 200, 220, 245, 260, 275, 290, 310, 330] },
]

interface DateAxisCellProps {
    title: string
    labels: string[]
    series: Series[]
    interval: TimeInterval
    timezone: string
}

function DateAxisCell({ title, labels, series, interval, timezone }: DateAxisCellProps): JSX.Element {
    const theme = useReactiveTheme()
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="text-xs text-muted">{title}</span>
            <Stage width={420} height={220}>
                <TimeSeriesLineChart
                    series={series}
                    labels={labels}
                    theme={theme}
                    config={{
                        xAxis: { timezone, interval },
                        yAxis: { showGrid: true },
                    }}
                />
            </Stage>
        </div>
    )
}

export const DateAxis: Story = {
    render: () => {
        const cells: { interval: TimeInterval; labels: string[]; series: Series[]; title: string }[] = [
            { interval: 'hour', labels: HOURLY_LABELS, series: HOURLY_SERIES, title: 'hour' },
            { interval: 'day', labels: DAILY_LABELS, series: DAILY_SERIES, title: 'day' },
            { interval: 'month', labels: MONTHLY_LABELS, series: MONTHLY_SERIES, title: 'month' },
        ]
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: 24 }}>
                {(['UTC', 'America/New_York'] as const).map((timezone) => (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div key={timezone} style={{ display: 'contents' }}>
                        {cells.map(({ interval, labels, series, title }) => (
                            <DateAxisCell
                                key={`${timezone}-${interval}`}
                                title={`${timezone} · ${title}`}
                                labels={labels}
                                series={series}
                                interval={interval}
                                timezone={timezone}
                            />
                        ))}
                    </div>
                ))}
            </div>
        )
    },
}

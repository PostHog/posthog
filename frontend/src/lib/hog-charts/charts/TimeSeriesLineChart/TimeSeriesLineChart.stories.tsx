import { Meta, StoryObj } from '@storybook/react'

import { TimeSeriesLineChart } from 'lib/hog-charts'
import type { Series, TimeInterval, YAxisConfig } from 'lib/hog-charts'
import { ciRanges } from 'lib/statistics'

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

interface YFormatCellProps {
    title: string
    config: YAxisConfig
    series: Series[]
}

function YFormatCell({ title, config, series }: YFormatCellProps): JSX.Element {
    const theme = useReactiveTheme()
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="text-xs text-muted">{title}</span>
            <Stage width={420} height={220}>
                <TimeSeriesLineChart
                    series={series}
                    labels={DAYS}
                    theme={theme}
                    config={{ yAxis: { ...config, showGrid: true } }}
                />
            </Stage>
        </div>
    )
}

const NUMERIC_SERIES: Series[] = [{ key: 'visits', label: 'Visits', data: [1200, 1350, 1280, 1600, 1450, 1700, 1520] }]
const PERCENTAGE_SERIES: Series[] = [{ key: 'rate', label: 'Conversion', data: [12, 18, 22, 31, 28, 35, 41] }]
const PERCENTAGE_SCALED_SERIES: Series[] = [
    { key: 'rate', label: 'Conversion', data: [0.12, 0.18, 0.22, 0.31, 0.28, 0.35, 0.41] },
]
const CURRENCY_SERIES: Series[] = [
    { key: 'revenue', label: 'Revenue', data: [1200, 1450, 1390, 1820, 1675, 2100, 1990] },
]
const DURATION_SERIES: Series[] = [{ key: 'session', label: 'Session length', data: [45, 90, 120, 180, 240, 300, 540] }]
const DURATION_MS_SERIES: Series[] = [{ key: 'latency', label: 'Latency', data: [120, 180, 240, 320, 410, 530, 680] }]

export const YAxisFormats: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, auto)', gap: 24 }}>
            <YFormatCell title="numeric" series={NUMERIC_SERIES} config={{ format: 'numeric' }} />
            <YFormatCell
                title="numeric · prefix + suffix"
                series={NUMERIC_SERIES}
                config={{ format: 'numeric', prefix: '$', suffix: ' req' }}
            />
            <YFormatCell title="short" series={NUMERIC_SERIES} config={{ format: 'short' }} />
            <YFormatCell title="percentage (0-100)" series={PERCENTAGE_SERIES} config={{ format: 'percentage' }} />
            <YFormatCell
                title="percentage_scaled (0-1)"
                series={PERCENTAGE_SCALED_SERIES}
                config={{ format: 'percentage_scaled' }}
            />
            <YFormatCell title="currency" series={CURRENCY_SERIES} config={{ format: 'currency', currency: 'USD' }} />
            <YFormatCell title="duration (s)" series={DURATION_SERIES} config={{ format: 'duration' }} />
            <YFormatCell title="duration_ms" series={DURATION_MS_SERIES} config={{ format: 'duration_ms' }} />
        </div>
    ),
}

const DERIVED_SERIES: Series[] = [
    { key: 'visits', label: 'Visits', data: [20, 35, 28, 60, 45, 70, 52] },
    { key: 'signups', label: 'Sign-ups', data: [4, 8, 6, 14, 11, 19, 13] },
]
const [DERIVED_CI_LOWER, DERIVED_CI_UPPER] = ciRanges(DERIVED_SERIES[0].data, 0.95)

export const ConfidenceIntervals: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={DERIVED_SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: { showGrid: true },
                        confidenceIntervals: [
                            { seriesKey: 'visits', lower: DERIVED_CI_LOWER, upper: DERIVED_CI_UPPER },
                        ],
                    }}
                />
            </Stage>
        )
    },
}

export const MovingAverage: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={DERIVED_SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: { showGrid: true },
                        movingAverage: [{ seriesKey: 'visits', window: 3 }],
                    }}
                />
            </Stage>
        )
    },
}

export const TrendLines: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={DERIVED_SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: { showGrid: true },
                        trendLines: [
                            { seriesKey: 'visits', kind: 'linear' },
                            { seriesKey: 'signups', kind: 'linear' },
                        ],
                    }}
                />
            </Stage>
        )
    },
}

export const ComparisonOf: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'visits', label: 'Visits', data: [20, 35, 28, 60, 45, 70, 52], color: theme.colors[0] },
            {
                key: 'visits-prev',
                label: 'Visits (previous)',
                data: [15, 25, 32, 40, 38, 50, 44],
                color: theme.colors[0],
            },
        ]
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={series}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: { showGrid: true },
                        comparisonOf: { 'visits-prev': 'visits' },
                    }}
                />
            </Stage>
        )
    },
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

import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import type { TimeInterval } from '../../utils/dates'
import { ciRanges } from '../../utils/statistics'
import type { YAxisConfig } from '../../utils/use-axis-formatters'
import {
    CURRENCY_SERIES,
    DAILY_LABELS,
    DAILY_SERIES,
    DAYS,
    DURATION_MS_SERIES,
    DURATION_SERIES,
    HOURLY_LABELS,
    HOURLY_SERIES,
    MONTHLY_LABELS,
    MONTHLY_SERIES,
    NUMERIC_SERIES,
    PERCENTAGE_SCALED_SERIES,
    PERCENTAGE_SERIES,
    SERIES,
} from '../time-series-fixtures'
import { TimeSeriesLineChart } from './TimeSeriesLineChart'

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

/** Two series on independent y-axes: revenue (currency, left) and conversion rate (percentage,
 *  right), each formatting its own ticks. Pass `yAxis` as an array — one entry per axis. */
export const DualYAxis: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'revenue', label: 'Revenue', color: '', data: [1100, 1300, 1250, 1700, 1500, 1900, 1800] },
            {
                key: 'conversion',
                label: 'Conversion',
                color: '',
                data: [0.022, 0.028, 0.025, 0.034, 0.031, 0.038, 0.036],
                yAxisId: 'right',
            },
        ]
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={series}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: [
                            { id: 'left', label: 'Revenue', format: 'currency', currency: 'USD', showGrid: true },
                            { id: 'right', position: 'right', label: 'Conversion', format: 'percentage_scaled' },
                        ],
                    }}
                />
            </Stage>
        )
    },
}

/** Mixed scale types across axes: a linear count on the left and a log-scaled latency series on
 *  the right, each with its own formatter. */
export const DualYAxisMixedScales: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const series: Series[] = [
            { key: 'requests', label: 'Requests', color: '', data: [120, 180, 150, 210, 170, 240, 220] },
            {
                key: 'latency',
                label: 'p99 latency',
                color: '',
                data: [12, 80, 35, 600, 90, 1400, 300],
                yAxisId: 'right',
            },
        ]
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={series}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: [
                            { id: 'left', label: 'Requests', format: 'short', showGrid: true },
                            { id: 'right', position: 'right', label: 'p99 latency', scale: 'log', suffix: 'ms' },
                        ],
                    }}
                />
            </Stage>
        )
    },
}

export const DragToZoom: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const [range, setRange] = useState<[string, string] | null>(null)
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <span className="text-xs text-muted">
                    {range ? `Selected: ${range[0]} → ${range[1]}` : 'Drag a horizontal range to zoom'}
                </span>
                <Stage>
                    <TimeSeriesLineChart
                        series={SERIES}
                        labels={DAYS}
                        theme={theme}
                        config={{ yAxis: { showGrid: true } }}
                        onDateRangeZoom={({ startLabel, endLabel }) => setRange([startLabel, endLabel])}
                    />
                </Stage>
            </div>
        )
    },
}

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
            <span className="text-xs text-muted-foreground">{title}</span>
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
            <span className="text-xs text-muted-foreground">{title}</span>
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

/** Offset, all-positive series: clamping leaves a tall empty gutter below the data; floating zooms
 *  onto the band so the day-to-day variation is legible. */
const OFFSET_SERIES: Series[] = [{ key: 'latency', label: 'p95 latency', data: [820, 860, 840, 905, 880, 930, 910] }]

/** `startAtZero` controls the baseline: the default (left) clamps a non-negative axis to 0; setting
 *  it `false` (right) floats the axis to the data range. */
export const StartAtZero: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, auto)', gap: 24 }}>
            <YFormatCell title="default (clamped to 0)" series={OFFSET_SERIES} config={{ suffix: ' ms' }} />
            <YFormatCell
                title="startAtZero: false (floated)"
                series={OFFSET_SERIES}
                config={{ suffix: ' ms', startAtZero: false }}
            />
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

/** Skeleton preview while a query runs: the known x-domain renders real date ticks, the marks
 *  are deterministic placeholders, and interactions are off. Pass the labels computed from the
 *  date range + interval so the axis matches what the loaded chart will show. */
export const Loading: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={[]}
                    labels={DAILY_LABELS}
                    theme={theme}
                    loading
                    config={{ xAxis: { interval: 'day', timezone: 'UTC' }, yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

/** Stale-while-revalidate: the current data stays rendered, dimmed, interactions off, with the
 *  shimmer marking the refetch. `loadingOverlay` centers host progress UI over the plot. */
export const Refreshing: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesLineChart
                    series={DAILY_SERIES}
                    labels={DAILY_LABELS}
                    theme={theme}
                    refreshing
                    loadingOverlay={<span>Updating…</span>}
                    config={{ xAxis: { interval: 'day', timezone: 'UTC' }, yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

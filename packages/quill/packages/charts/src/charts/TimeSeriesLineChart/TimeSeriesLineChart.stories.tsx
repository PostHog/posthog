import { Meta, StoryObj } from '@storybook/react'
import { useState } from 'react'

import { ChartHoverSync } from '../../core/hover-sync'
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
import { TimeSeriesLineChart, type TimeSeriesLineChartConfig } from './TimeSeriesLineChart'

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
    interval?: TimeInterval
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

/** `min` / `max` pin either end of the axis. Either may be omitted to keep the automatic bound, so
 *  a lone `min` reads as "only show me above this". */
export const YAxisRange: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: 24 }}>
            <YFormatCell title="automatic" series={OFFSET_SERIES} config={{ suffix: ' ms' }} />
            <YFormatCell title="min: 800" series={OFFSET_SERIES} config={{ suffix: ' ms', min: 800 }} />
            <YFormatCell
                title="min: 800, max: 1000"
                series={OFFSET_SERIES}
                config={{ suffix: ' ms', min: 800, max: 1000 }}
            />
        </div>
    ),
}

const AREA_SERIES: Series[] = [
    { key: 'p50', label: 'p50', data: [120, 140, 130, 160, 150, 170, 155], fill: { opacity: 0.2 } },
    { key: 'p90', label: 'p90', data: [220, 260, 240, 300, 280, 320, 290], fill: { opacity: 0.2 } },
    { key: 'p99', label: 'p99', data: [400, 460, 430, 520, 480, 560, 510], fill: { opacity: 0.2 } },
]

function StackingCell({ title, series, stacked }: { title: string; series: Series[]; stacked?: boolean }): JSX.Element {
    const theme = useReactiveTheme()
    return (
        <div>
            <div>{title}</div>
            <Stage width={360} height={220}>
                <TimeSeriesLineChart
                    series={series}
                    labels={DAYS}
                    theme={theme}
                    config={{ stacked, yAxis: { showGrid: true } }}
                />
            </Stage>
        </div>
    )
}

/** Two or more `fill` series stack by default. `stacked: false` overlaps them at their own values,
 *  and `stacked: false` on one series keeps it out of the stack (here a total line on top of a
 *  stacked breakdown). */
export const Stacking: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, auto)', gap: 24 }}>
            <StackingCell title="default (stacked)" series={AREA_SERIES} />
            <StackingCell title="stacked: false" series={AREA_SERIES} stacked={false} />
            <StackingCell
                title="series stacked: false"
                series={[
                    ...SERIES.map((s) => ({ ...s, fill: { opacity: 0.3 } })),
                    {
                        key: 'total',
                        label: 'Total',
                        data: SERIES[0].data.map((_, i) => SERIES.reduce((sum, s) => sum + s.data[i], 0)),
                        stacked: false,
                        visibility: { total: false },
                        stroke: { pattern: [6, 4] },
                    },
                ]}
            />
        </div>
    ),
}

const LATENCY_SERIES: Series[] = [
    { key: 'api', label: 'api', data: [120, 140, 130, 160, 150, 170, 155] },
    { key: 'web', label: 'web', data: [220, 260, 240, 300, 280, 320, 290] },
    { key: 'worker', label: 'worker', data: [400, 460, 430, NaN, 480, 560, 510] },
    { key: 'cron', label: 'cron', data: [60, 65, 58, 72, 70, 66, 61] },
]

/** `legend.values` turns the legend into a table of per-series summaries, formatted like the axis.
 *  Click a header to sort by it; rows still isolate and toggle their series. */
export const LegendValues: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            // eslint-disable-next-line react/forbid-dom-props
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, auto)', gap: 24 }}>
                {(['bottom', 'right'] as const).map((position) => (
                    <Stage key={position} width={560} height={320}>
                        <TimeSeriesLineChart
                            series={LATENCY_SERIES}
                            labels={DAYS}
                            theme={theme}
                            config={{
                                yAxis: { showGrid: true, suffix: ' ms' },
                                legend: {
                                    show: true,
                                    position,
                                    values: ['mean', 'max', 'last'],
                                    sortBy: 'mean',
                                },
                            }}
                        />
                    </Stage>
                ))}
            </div>
        )
    },
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
        const cells: { interval?: TimeInterval; labels: string[]; series: Series[]; title: string }[] = [
            { interval: 'hour', labels: HOURLY_LABELS, series: HOURLY_SERIES, title: 'hour' },
            { labels: DAILY_LABELS, series: DAILY_SERIES, title: 'day (inferred)' },
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

const SYNC_HOURS = Array.from({ length: 24 }, (_, i) => `2026-03-01T${String(i).padStart(2, '0')}:00:00Z`)
const SYNC_HALF_HOURS = Array.from(
    { length: 48 },
    (_, i) => `2026-03-01T${String(Math.floor(i / 2)).padStart(2, '0')}:${i % 2 ? '30' : '00'}:00Z`
)

/** Charts inside a `ChartHoverSync` share the hovered x: hovering one draws a crosshair at the same
 *  time on the others, even when their points sit on different grids (hourly above, half-hourly
 *  below). Only the hovered chart shows its tooltip. */
export const SyncedHover: Story = {
    render: () => {
        const theme = useReactiveTheme()
        const config = { xAxis: { timezone: 'UTC', interval: 'hour' as const }, yAxis: { showGrid: true } }
        return (
            <ChartHoverSync>
                {/* eslint-disable-next-line react/forbid-dom-props */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    <Stage height={200}>
                        <TimeSeriesLineChart
                            series={[
                                {
                                    key: 'rps',
                                    label: 'Requests',
                                    data: SYNC_HOURS.map((_, i) => 200 + 80 * Math.sin(i / 3)),
                                },
                            ]}
                            labels={SYNC_HOURS}
                            theme={theme}
                            config={config}
                        />
                    </Stage>
                    <Stage height={200}>
                        <TimeSeriesLineChart
                            series={[
                                {
                                    key: 'p99',
                                    label: 'p99',
                                    data: SYNC_HALF_HOURS.map((_, i) => 120 + 40 * Math.cos(i / 5)),
                                },
                            ]}
                            labels={SYNC_HALF_HOURS}
                            theme={theme}
                            config={config}
                        />
                    </Stage>
                </div>
            </ChartHoverSync>
        )
    },
}

// Hourly samples with hours 06-11 absent and a missing value at 15:00.
const SPARSE_HOURS = [0, 1, 2, 3, 4, 5, 12, 13, 14, 15, 16, 17, 18, 19, 20]
const SPARSE_LABELS = SPARSE_HOURS.map((h) => `2026-03-01T${String(h).padStart(2, '0')}:00:00Z`)
const SPARSE_SERIES: Series[] = [
    {
        key: 'rps',
        label: 'Requests',
        data: SPARSE_HOURS.map((h) => (h === 15 ? NaN : 200 + 60 * Math.sin(h / 3))),
        fill: { opacity: 0.2 },
    },
]

function TimeScaleCell({ title, config }: { title: string; config: TimeSeriesLineChartConfig }): JSX.Element {
    const theme = useReactiveTheme()
    return (
        <div>
            <div>{title}</div>
            <Stage width={420} height={200}>
                <TimeSeriesLineChart
                    series={SPARSE_SERIES}
                    labels={SPARSE_LABELS}
                    theme={theme}
                    config={{ xAxis: { timezone: 'UTC', interval: 'hour' }, yAxis: { showGrid: true }, ...config }}
                />
            </Stage>
        </div>
    )
}

/** `xScale: 'time'` places points by time, so the missing morning keeps its width instead of being
 *  squeezed out. `xDomain` spans a range wider than the data. `connectNulls: true` bridges every
 *  gap; a number of milliseconds bridges only gaps that short, so the 2-hour hole at 15:00 joins
 *  while the 7-hour morning gap stays open. */
export const TimeScale: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, auto)', gap: 24 }}>
            <TimeScaleCell title="default (index)" config={{}} />
            <TimeScaleCell title="xScale: 'time'" config={{ xScale: 'time' }} />
            <TimeScaleCell
                title="xScale: 'time', xDomain: whole day, connectNulls: 2h"
                config={{
                    xScale: 'time',
                    xDomain: [Date.parse('2026-03-01T00:00:00Z'), Date.parse('2026-03-02T00:00:00Z')],
                    connectNulls: 2 * 60 * 60 * 1000,
                }}
            />
            <TimeScaleCell title="xScale: 'time', connectNulls: true" config={{ xScale: 'time', connectNulls: true }} />
        </div>
    ),
}

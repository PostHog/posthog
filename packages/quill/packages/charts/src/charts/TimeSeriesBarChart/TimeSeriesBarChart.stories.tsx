import { Meta, StoryObj } from '@storybook/react'

import type { Series } from '../../core/types'
import { Stage, useReactiveTheme } from '../../story-helpers'
import type { TimeInterval } from '../../utils/dates'
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
import { TimeSeriesBarChart } from './TimeSeriesBarChart'

const meta: Meta = {
    title: 'Components/HogCharts/TimeSeriesBarChart',
    parameters: { layout: 'centered' },
}
export default meta

type Story = StoryObj<{}>

export const Basic: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

export const Grouped: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ barLayout: 'grouped', yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

const LONG_CATEGORY_LABELS = [
    '/api/projects/alpha/insights/daily-active-users',
    '/api/projects/beta/insights/weekly-retention',
    '/api/projects/gamma/insights/conversion-funnel',
]
const LONG_CATEGORY_SERIES: Series[] = [{ key: 'requests', label: 'Requests', data: [420, 315, 510] }]

export const RotatedCategoryLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage width={720} height={420}>
                <TimeSeriesBarChart
                    series={LONG_CATEGORY_SERIES}
                    labels={LONG_CATEGORY_LABELS}
                    theme={theme}
                    config={{ xAxis: { tickLabelRotation: -45 }, yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

// Grouped bars whose series span very different magnitudes — each is scaled against its own
// y-axis (`yAxisId`) so all three stay individually legible instead of the small series being
// flattened against the large one. Mirrors the legacy "show multiple y-axes" trends option.
const MULTI_AXIS_SERIES: Series[] = [
    { key: 'sessions', label: 'Sessions', data: [70, 78, 72, 88, 75, 90, 80] },
    { key: 'pageviews', label: 'Pageviews', data: [140, 168, 150, 184, 160, 178, 170], yAxisId: 'y1' },
    { key: 'events', label: 'Events', data: [3500, 4200, 3600, 4500, 3800, 4100, 4000], yAxisId: 'y2' },
]

export const GroupedMultipleYAxes: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={MULTI_AXIS_SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ barLayout: 'grouped', yAxis: { showGrid: true } }}
                />
            </Stage>
        )
    },
}

export const Percent: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{ barLayout: 'percent', yAxis: { showGrid: true } }}
                />
            </Stage>
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
                <TimeSeriesBarChart
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
                <TimeSeriesBarChart
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

// Single occurrences (1) alongside a spike three orders of magnitude taller (1400) — without
// minBarSize the small bars collapse to a sub-pixel sliver next to the spike.
const MIN_BAR_SIZE_SERIES: Series[] = [{ key: 'errors', label: 'Errors', data: [1, 0, 2, 1400, 3, 0, 1] }]

interface MinBarSizeCellProps {
    title: string
    series: Series[]
    minBarSize?: number
}

function MinBarSizeCell({ title, series, minBarSize }: MinBarSizeCellProps): JSX.Element {
    const theme = useReactiveTheme()
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="text-xs text-muted-foreground">{title}</span>
            <Stage>
                <TimeSeriesBarChart series={series} labels={DAYS} theme={theme} config={{ minBarSize }} />
            </Stage>
        </div>
    )
}

/** `minBarSize` floors each non-zero bar's thickness along the value axis, so single-occurrence
 *  buckets stay visible next to a spike three orders of magnitude taller. Empty buckets stay empty. */
export const MinBarSize: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, auto)', gap: 24 }}>
            <MinBarSizeCell title="default" series={MIN_BAR_SIZE_SERIES} />
            <MinBarSizeCell title="minBarSize: 6" series={MIN_BAR_SIZE_SERIES} minBarSize={6} />
        </div>
    ),
}

// A max of 246 nices up to 300–400 depending on plot height, so without the pin the tallest bar
// stops well short of the plot top.
const PINNED_DOMAIN_SERIES: Series[] = [{ key: 'volume', label: 'Volume', data: [0, 246, 0, 12, 0, 3, 0] }]

function PinnedValueDomainCell({ title, pinned }: { title: string; pinned: boolean }): JSX.Element {
    const theme = useReactiveTheme()
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span className="text-xs text-muted-foreground">{title}</span>
            <Stage>
                <TimeSeriesBarChart
                    series={PINNED_DOMAIN_SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: { hide: true },
                        minBarSize: 2,
                        valueDomain: pinned ? { min: 0, max: 246 } : undefined,
                    }}
                />
            </Stage>
        </div>
    )
}

/** A fixed `valueDomain` skips `d3.nice()`, so `[0, dataMax]` makes the tallest bar reach the plot
 *  top — the sparkline treatment, where the hidden axis makes nice-rounded headroom pure waste. */
export const PinnedValueDomain: Story = {
    render: () => (
        // eslint-disable-next-line react/forbid-dom-props
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, auto)', gap: 24 }}>
            <PinnedValueDomainCell title="default (niced headroom)" pinned={false} />
            <PinnedValueDomainCell title="valueDomain: { min: 0, max: dataMax }" pinned />
        </div>
    ),
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

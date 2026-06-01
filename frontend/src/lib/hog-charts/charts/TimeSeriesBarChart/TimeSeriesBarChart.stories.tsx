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
            <span className="text-xs text-muted">{title}</span>
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
            <span className="text-xs text-muted">{title}</span>
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

export const WithGoalLine: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={SERIES}
                    labels={DAYS}
                    theme={theme}
                    config={{
                        yAxis: { showGrid: true },
                        goalLines: [{ value: 50, label: 'Target' }],
                    }}
                />
            </Stage>
        )
    },
}

export const WithValueLabels: Story = {
    render: () => {
        const theme = useReactiveTheme()
        return (
            <Stage>
                <TimeSeriesBarChart
                    series={[SERIES[0]]}
                    labels={DAYS}
                    theme={theme}
                    config={{ yAxis: { showGrid: true }, valueLabels: true }}
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

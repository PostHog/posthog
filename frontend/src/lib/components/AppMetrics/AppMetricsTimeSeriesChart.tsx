import clsx from 'clsx'
import { useMemo } from 'react'

import {
    type Series,
    TimeSeriesLineChart,
    type TimeSeriesLineChartConfig,
    createXAxisTickCallback,
} from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { dayjs } from 'lib/dayjs'

import { AppMetricsTimeSeriesResponse } from './appMetricsLogic'

export interface AppMetricsSeriesOverride {
    label?: string
    color?: string
}

export interface AppMetricsTimeSeriesChartProps {
    timeSeries: AppMetricsTimeSeriesResponse
    className?: string
    /** Display label and color per series name. Unset colors fall back to the theme palette. */
    seriesOverrides?: Record<string, AppMetricsSeriesOverride>
    showLegend?: boolean
    /** Hide axes, ticks and grid lines for compact summary tiles. */
    minimal?: boolean
}

export function AppMetricsTimeSeriesChart({
    timeSeries,
    className,
    seriesOverrides,
    showLegend = false,
    minimal = false,
}: AppMetricsTimeSeriesChartProps): JSX.Element {
    const theme = useChartTheme()

    const series = useMemo<Series[]>(
        () =>
            timeSeries.series.map((s) => {
                const override = seriesOverrides?.[s.name]
                return {
                    key: s.name,
                    label: override?.label ?? s.name,
                    data: s.values,
                    ...(override?.color ? { color: override.color } : {}),
                }
            }),
        [timeSeries.series, seriesOverrides]
    )

    const labels = timeSeries.labels
    const config = useChartConfig<TimeSeriesLineChartConfig>(() => {
        // Labels arrive from appMetricsLogic pre-formatted in the team's timezone ('YYYY-MM-DD',
        // or 'YYYY-MM-DD HH:mm' for sub-day intervals), so parse them as naive local strings.
        const hasTimePart = labels.some((label) => label.includes(' '))
        return {
            xAxis: {
                hide: minimal,
                tickFormatter: createXAxisTickCallback({ allDays: labels, timezone: 'UTC' }),
            },
            yAxis: { hide: minimal, showGrid: !minimal },
            ...(minimal ? { showAxisLines: { x: false, y: false } as const } : {}),
            legend: { show: showLegend, position: 'top', interactive: true },
            tooltip: {
                placement: 'cursor',
                pinnable: true,
                sortedByValue: true,
                labelFormatter: (label: string) => dayjs(label).format(hasTimePart ? 'MMM D, HH:mm' : 'MMM D, YYYY'),
            },
        }
    }, [labels, minimal, showLegend])

    return (
        <div className={clsx('relative flex h-full w-full flex-col', className)}>
            <TimeSeriesLineChart series={series} labels={labels} theme={theme} config={config} />
        </div>
    )
}

import { useMemo } from 'react'

import { TimeSeriesLineChart } from '@posthog/quill-charts'
import type { TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'

import type { ManagedWarehouseMonitoringSeriesResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { buildMonitoringChartData } from './monitoringChartData'
import type { MonitoringChartMetricConfig } from './monitoringChartData'

export function MonitoringChart({
    title,
    description,
    responses,
    metrics,
    yAxis,
    valueFormatter,
    loading,
}: {
    title: string
    description: string
    responses: ManagedWarehouseMonitoringSeriesResponseApi[]
    metrics: MonitoringChartMetricConfig[]
    yAxis?: TimeSeriesLineChartConfig['yAxis']
    valueFormatter?: (value: number) => string
    loading: boolean
}): JSX.Element {
    const theme = useChartTheme()
    const data = useMemo(() => buildMonitoringChartData(responses, metrics), [responses, metrics])
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { timezone: 'UTC' },
            yAxis,
            legend: { show: data.series.length > 1, interactive: true, position: 'bottom' },
            tooltip: { placement: 'cursor', sortedByValue: true, valueFormatter },
        }),
        [data.series.length, valueFormatter, yAxis]
    )

    return (
        <LemonCard hoverEffect={false} className="flex min-h-80 flex-col p-4">
            <div className="mb-4">
                <h3 className="mb-1">{title}</h3>
                <p className="mb-0 text-xs text-muted">{description}</p>
            </div>
            {loading && !data.labels.length ? (
                <LemonSkeleton className="h-64 w-full" />
            ) : data.labels.length && data.series.length ? (
                <div className="flex h-64 flex-col">
                    <TimeSeriesLineChart series={data.series} labels={data.labels} theme={theme} config={config} />
                </div>
            ) : (
                <div className="flex h-64 items-center justify-center text-muted">No data in this time range.</div>
            )}
        </LemonCard>
    )
}

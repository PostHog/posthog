import { useMemo } from 'react'

import { Skeleton, Text } from '@posthog/quill'
import { TimeSeriesLineChart, type Series, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import type { ManagedWarehouseMonitoringSeriesResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { buildMonitoringChartData, type MonitoringChartMetricConfig } from '../DataOpsScene/tabs/monitoringChartData'
import { chartByteUnit, formatAxisBytes, formatBytes } from '../WarehouseConsole/warehouseConsoleFormat'
import { WarehouseResourceError } from '../WarehouseConsole/WarehouseResourceError'
import { WarehouseSection } from '../WarehouseConsole/WarehouseSection'

export interface WarehousePerformanceChartProps {
    title: string
    description: string
    responses: ManagedWarehouseMonitoringSeriesResponseApi[]
    metrics: MonitoringChartMetricConfig[]
    /** `bytes_per_second` plots in one binary unit, so the axis ticks are round numbers. */
    unit?: 'bytes_per_second'
    yAxisFormat?: 'percentage_scaled' | 'duration'
    /** Formats a tooltip value in the metric's own unit. */
    valueFormatter?: (value: number) => string
    loading: boolean
    failed: boolean
    onRetry: () => void
    'data-attr': string
}

/** One time series chart of the Performance tab, in a section with loading, empty and error states. */
export function WarehousePerformanceChart({
    title,
    description,
    responses,
    metrics,
    unit,
    yAxisFormat,
    valueFormatter,
    loading,
    failed,
    onRetry,
    'data-attr': dataAttr,
}: WarehousePerformanceChartProps): JSX.Element {
    const theme = useChartTheme()
    const data = useMemo(() => buildMonitoringChartData(responses, metrics), [responses, metrics])
    const byteUnit = useMemo(
        () =>
            unit === 'bytes_per_second'
                ? chartByteUnit(Math.max(0, ...data.series.flatMap((series) => series.data.filter(Number.isFinite))))
                : null,
        [data.series, unit]
    )
    const series = useMemo<Series[]>(
        () =>
            byteUnit
                ? data.series.map((item) => ({ ...item, data: item.data.map((value) => value / byteUnit.divisor) }))
                : data.series,
        [data.series, byteUnit]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(
        () => ({
            xAxis: { timezone: 'UTC' },
            yAxis: byteUnit
                ? { tickFormatter: (value: number) => `${formatAxisBytes(value, byteUnit)}/s`, startAtZero: true }
                : yAxisFormat
                  ? { format: yAxisFormat }
                  : undefined,
            legend: { show: series.length > 1, interactive: true, position: 'bottom' },
            tooltip: {
                placement: 'cursor',
                sortedByValue: true,
                valueFormatter: byteUnit
                    ? (value: number) => `${formatBytes(value * byteUnit.divisor)}/s`
                    : valueFormatter,
            },
        }),
        [series.length, byteUnit, yAxisFormat, valueFormatter]
    )

    let body: JSX.Element
    if (failed && !data.labels.length) {
        body = (
            <WarehouseResourceError
                title="Couldn't load this chart"
                onRetry={onRetry}
                data-attr={`${dataAttr}-retry`}
            />
        )
    } else if (loading && !data.labels.length) {
        body = <Skeleton className="h-56 w-full" />
    } else if (data.labels.length && series.length) {
        body = (
            <div className="flex h-56 w-full flex-col">
                <TimeSeriesLineChart series={series} labels={data.labels} theme={theme} config={config} />
            </div>
        )
    } else {
        body = (
            <div className="flex h-56 items-center justify-center">
                <Text size="sm" variant="muted">
                    No data in this time range.
                </Text>
            </div>
        )
    }

    return (
        <WarehouseSection title={title} description={description} data-attr={dataAttr}>
            {body}
        </WarehouseSection>
    )
}

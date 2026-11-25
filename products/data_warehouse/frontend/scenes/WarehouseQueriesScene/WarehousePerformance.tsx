import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { IconRefresh } from '@posthog/icons'
import { Button, Heading } from '@posthog/quill'

import {
    managedWarehouseTrinoMonitoringLogic,
    TRINO_MONITORING_WINDOW_OPTIONS,
    type TrinoMonitoringWindow,
} from '../DataOpsScene/tabs/managedWarehouseTrinoMonitoringLogic'
import { formatDuration } from '../WarehouseConsole/warehouseConsoleFormat'
import { type SegmentedOption, WarehouseSegmentedControl } from '../WarehouseConsole/WarehouseSegmentedControl'
import { WarehousePerformanceChart } from './WarehousePerformanceChart'

// pinned: the data-attr values and analytics event names in this file feed autocapture and dashboards, so renaming them breaks both.

const RANGE_OPTIONS: SegmentedOption<TrinoMonitoringWindow>[] = TRINO_MONITORING_WINDOW_OPTIONS.map((option) => ({
    value: option.value,
    label: option.label,
    'data-attr': `warehouse-performance-range-${option.value}`,
}))

const formatRate = (value: number): string => `${Number(value.toFixed(2)).toLocaleString('en-US')}/s`
const formatPercentValue = (value: number): string => `${Number((value * 100).toFixed(1))}%`
const formatSeconds = (value: number): string => formatDuration(value * 1000)
const formatNumber = (value: number): string => Number(value.toFixed(2)).toLocaleString('en-US')

// Chart metric lists are declared once, so the charts keep stable props between refreshes.
const QUERY_RATE = [{ metric: 'query_rate', fallbackLabel: 'Queries' }]
const ERROR_RATIO = [{ metric: 'error_ratio', fallbackLabel: 'Errors' }]
const DURATION = [
    { metric: 'duration_p50', fallbackLabel: 'p50' },
    { metric: 'duration_p95', fallbackLabel: 'p95' },
]
const IN_FLIGHT = [{ metric: 'queries_in_flight', fallbackLabel: 'Queries' }]
const QUEUE_TIME = [{ metric: 'queue_time_p95', fallbackLabel: 'p95' }]
const SCANNED = [{ metric: 'scanned_bytes_rate', fallbackLabel: 'Scanned' }]
const CPU = [{ metric: 'cpu_seconds_rate', fallbackLabel: 'CPU' }]

export function WarehousePerformance(): JSX.Element {
    const {
        monitoringSeries,
        monitoringWindow,
        monitoringSeriesLoading,
        initialMonitoringSeriesLoading,
        monitoringSeriesError,
    } = useValues(managedWarehouseTrinoMonitoringLogic)
    const { setMonitoringWindow, refreshMonitoring } = useActions(managedWarehouseTrinoMonitoringLogic)

    const shared = {
        responses: monitoringSeries,
        loading: initialMonitoringSeriesLoading,
        failed: monitoringSeriesError,
        onRetry: refreshMonitoring,
    }

    return (
        <>
            <div className="flex flex-wrap items-center justify-between gap-2">
                <WarehouseSegmentedControl
                    value={monitoringWindow}
                    options={RANGE_OPTIONS}
                    onChange={(value) => {
                        posthog.capture('warehouse performance range changed', { range: value })
                        setMonitoringWindow(value)
                    }}
                    label="Time range"
                />
                <Button
                    loading={monitoringSeriesLoading}
                    disabled={monitoringSeriesLoading}
                    onClick={() => {
                        posthog.capture('warehouse performance refresh clicked')
                        refreshMonitoring()
                    }}
                    data-attr="warehouse-performance-refresh"
                >
                    <IconRefresh />
                    Refresh
                </Button>
            </div>

            <section aria-labelledby="warehouse-performance-health" className="flex flex-col gap-2">
                <Heading render={<h2 id="warehouse-performance-health" />} size="base" className="m-0">
                    Query health
                </Heading>
                <div className="grid grid-cols-1 gap-3 @3xl/warehouse-queries:grid-cols-2 @3xl/warehouse-queries:[&>*:last-child:nth-child(odd)]:col-span-2">
                    <WarehousePerformanceChart
                        title="Query rate"
                        description="Queries per second, by outcome"
                        metrics={QUERY_RATE}
                        valueFormatter={formatRate}
                        data-attr="warehouse-performance-query-rate"
                        {...shared}
                    />
                    <WarehousePerformanceChart
                        title="Error ratio"
                        description="Share of queries that returned an error"
                        metrics={ERROR_RATIO}
                        yAxisFormat="percentage_scaled"
                        valueFormatter={formatPercentValue}
                        data-attr="warehouse-performance-error-ratio"
                        {...shared}
                    />
                    <WarehousePerformanceChart
                        title="Duration"
                        description="Median and p95 query duration"
                        metrics={DURATION}
                        yAxisFormat="duration"
                        valueFormatter={formatSeconds}
                        data-attr="warehouse-performance-duration"
                        {...shared}
                    />
                </div>
            </section>

            <section aria-labelledby="warehouse-performance-load" className="flex flex-col gap-2">
                <Heading render={<h2 id="warehouse-performance-load" />} size="base" className="m-0">
                    Load
                </Heading>
                <div className="grid grid-cols-1 gap-3 @3xl/warehouse-queries:grid-cols-2">
                    <WarehousePerformanceChart
                        title="Queries in flight"
                        description="Queries not yet finished, by state"
                        metrics={IN_FLIGHT}
                        valueFormatter={formatNumber}
                        data-attr="warehouse-performance-in-flight"
                        {...shared}
                    />
                    <WarehousePerformanceChart
                        title="Queue time"
                        description="p95 time a query waits before it runs"
                        metrics={QUEUE_TIME}
                        yAxisFormat="duration"
                        valueFormatter={formatSeconds}
                        data-attr="warehouse-performance-queue-time"
                        {...shared}
                    />
                    <WarehousePerformanceChart
                        title="Data scanned"
                        description="Bytes read per second by finished queries"
                        metrics={SCANNED}
                        unit="bytes_per_second"
                        data-attr="warehouse-performance-scanned"
                        {...shared}
                    />
                    <WarehousePerformanceChart
                        title="CPU time"
                        description="CPU seconds used per second by finished queries"
                        metrics={CPU}
                        valueFormatter={formatNumber}
                        data-attr="warehouse-performance-cpu"
                        {...shared}
                    />
                </div>
            </section>
        </>
    )
}

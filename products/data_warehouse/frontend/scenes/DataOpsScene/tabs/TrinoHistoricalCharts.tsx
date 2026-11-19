import { memo } from 'react'

import { humanFriendlyDuration } from 'lib/utils/durations'
import { humanFriendlyNumber, humanizeBytes, percentage } from 'lib/utils/numbers'

import type { ManagedWarehouseMonitoringSeriesResponseApi } from 'products/data_warehouse/frontend/generated/api.schemas'

import { MonitoringChart } from './MonitoringChart'
import { MonitoringSection } from './MonitoringSection'

interface TrinoHistoricalChartsProps {
    monitoringSeries: ManagedWarehouseMonitoringSeriesResponseApi[]
    initialLoading: boolean
}

export const TrinoHistoricalCharts = memo(function TrinoHistoricalCharts({
    monitoringSeries,
    initialLoading,
}: TrinoHistoricalChartsProps): JSX.Element {
    return (
        <>
            <MonitoringSection
                title="Query health"
                description="Query volume, failures, and duration for the selected time range."
            >
                <div className="@container">
                    <div className="grid grid-cols-1 gap-4 @5xl:grid-cols-3">
                        <MonitoringChart
                            title="Query rate"
                            description="Queries per second, split by outcome"
                            responses={monitoringSeries}
                            metrics={[{ metric: 'query_rate', fallbackLabel: 'Queries' }]}
                            valueFormatter={(value) => `${humanFriendlyNumber(value)}/s`}
                            loading={initialLoading}
                        />
                        <MonitoringChart
                            title="Query error ratio"
                            description="Share of queries that returned an error"
                            responses={monitoringSeries}
                            metrics={[{ metric: 'error_ratio', fallbackLabel: 'Errors' }]}
                            yAxis={{ format: 'percentage_scaled' }}
                            valueFormatter={(value) => percentage(value)}
                            loading={initialLoading}
                        />
                        <MonitoringChart
                            title="Query duration"
                            description="Median and p95 query duration"
                            responses={monitoringSeries}
                            metrics={[
                                { metric: 'duration_p50', fallbackLabel: 'p50' },
                                { metric: 'duration_p95', fallbackLabel: 'p95' },
                            ]}
                            yAxis={{ format: 'duration' }}
                            valueFormatter={(value) => humanFriendlyDuration(value, { secondsPrecision: 2 })}
                            loading={initialLoading}
                        />
                    </div>
                </div>
            </MonitoringSection>

            <MonitoringSection
                title="Load"
                description="How much work the warehouse is doing, and how long queries wait."
            >
                <div className="@container">
                    <div className="grid grid-cols-1 gap-4 @5xl:grid-cols-2">
                        <MonitoringChart
                            title="Queries in flight"
                            description="Queries not yet finished, by state"
                            responses={monitoringSeries}
                            metrics={[{ metric: 'queries_in_flight', fallbackLabel: 'Queries' }]}
                            valueFormatter={(value) => humanFriendlyNumber(value)}
                            loading={initialLoading}
                        />
                        <MonitoringChart
                            title="Queue time"
                            description="p95 time a query waits before it runs"
                            responses={monitoringSeries}
                            metrics={[{ metric: 'queue_time_p95', fallbackLabel: 'p95' }]}
                            yAxis={{ format: 'duration' }}
                            valueFormatter={(value) => humanFriendlyDuration(value, { secondsPrecision: 2 })}
                            loading={initialLoading}
                        />
                        <MonitoringChart
                            title="Data scanned"
                            description="Bytes read from storage per second by finished queries"
                            responses={monitoringSeries}
                            metrics={[{ metric: 'scanned_bytes_rate', fallbackLabel: 'Scanned' }]}
                            yAxis={{ tickFormatter: (value: number) => `${humanizeBytes(value)}/s` }}
                            valueFormatter={(value) => `${humanizeBytes(value)}/s`}
                            loading={initialLoading}
                        />
                        <MonitoringChart
                            title="CPU time"
                            description="CPU seconds used per second by finished queries"
                            responses={monitoringSeries}
                            metrics={[{ metric: 'cpu_seconds_rate', fallbackLabel: 'CPU' }]}
                            valueFormatter={(value) => humanFriendlyNumber(value)}
                            loading={initialLoading}
                        />
                    </div>
                </div>
            </MonitoringSection>

            <MonitoringSection title="Storage" description="Tracked warehouse storage over time.">
                <div className="grid grid-cols-1 gap-4">
                    <MonitoringChart
                        title="Tracked storage"
                        description="Current warehouse data stored in object storage"
                        responses={monitoringSeries}
                        metrics={[{ metric: 'storage_bytes', fallbackLabel: 'Storage' }]}
                        yAxis={{ tickFormatter: (value: number) => humanizeBytes(value) }}
                        valueFormatter={humanizeBytes}
                        loading={initialLoading}
                    />
                </div>
            </MonitoringSection>
        </>
    )
})

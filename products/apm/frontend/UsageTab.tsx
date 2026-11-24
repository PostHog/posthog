import { useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumn, LemonTableColumns } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { applicationObservabilityLogic } from './applicationObservabilityLogic'
import type { ServiceUsageApi, UsageValuesApi } from './generated/api.schemas'
import { TelemetryLinks, TelemetrySignal } from './TelemetryLinks'
import { formatBytes, formatShare } from './usageDisplay'

type UsageField = keyof UsageValuesApi

function usageColumn(
    field: UsageField,
    title: string,
    tooltip: string,
    format: (value: number) => string,
    totals: UsageValuesApi | undefined,
    withShare: boolean
): LemonTableColumn<ServiceUsageApi, keyof ServiceUsageApi | undefined> {
    return {
        title,
        tooltip,
        dataIndex: field,
        align: 'right',
        sorter: (a, b) => a[field] - b[field],
        render: (_, row) => {
            if (!row[field]) {
                return <span className="text-muted">-</span>
            }
            const share = withShare && totals ? formatShare(row[field], totals[field]) : null
            return (
                <span className="font-mono whitespace-nowrap">
                    {format(row[field])}
                    {share ? <span className="text-muted ml-1">({share})</span> : null}
                </span>
            )
        },
    }
}

function signalsOf(row: ServiceUsageApi): TelemetrySignal[] {
    const signals: TelemetrySignal[] = []
    if (row.log_records > 0) {
        signals.push('logs')
    }
    if (row.spans > 0) {
        signals.push('traces')
    }
    if (row.metric_points > 0) {
        signals.push('metrics')
    }
    return signals
}

export function UsageTab(): JSX.Element {
    const { serviceUsage, usageRows, serviceUsageLoading, usageLoadError, timeRange } =
        useValues(applicationObservabilityLogic)
    const totals = serviceUsage?.totals
    const unavailable = serviceUsage?.unavailable_signals ?? []

    const columns: LemonTableColumns<ServiceUsageApi> = [
        {
            title: 'Service',
            key: 'service_name',
            render: (_, row) => <span className="font-semibold whitespace-nowrap">{row.service_name}</span>,
        },
        usageColumn(
            'log_bytes',
            'Logs size',
            'Uncompressed size of the stored logs. Billing counts logs by this size.',
            formatBytes,
            totals,
            true
        ),
        usageColumn(
            'log_records',
            'Log lines',
            'Log records stored in the time range.',
            humanFriendlyNumber,
            totals,
            false
        ),
        usageColumn(
            'spans',
            'Spans',
            'Spans of every kind stored in the time range.',
            humanFriendlyNumber,
            totals,
            true
        ),
        usageColumn(
            'metric_points',
            'Metric points',
            'Metric data points stored in the time range.',
            humanFriendlyNumber,
            totals,
            true
        ),
        usageColumn(
            'metric_series',
            'Metric series',
            'Distinct metric series active in the time range. More series means more points to store.',
            humanFriendlyNumber,
            totals,
            false
        ),
        {
            title: 'Open in',
            key: 'links',
            render: (_, row) => (
                <span className="flex gap-2">
                    <TelemetryLinks
                        serviceName={row.service_name}
                        timeRange={timeRange}
                        source="usage"
                        signals={signalsOf(row)}
                    />
                </span>
            ),
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            {usageLoadError ? (
                <LemonBanner type="error">
                    {usageRows.length > 0
                        ? "Couldn't refresh usage. Showing the last successful results."
                        : "Couldn't load usage. Try again shortly."}
                </LemonBanner>
            ) : unavailable.length > 0 ? (
                <LemonBanner type="warning">
                    Couldn't load {unavailable.join(' and ')} usage for this time range, so those columns show no
                    values. Try a shorter time range.
                </LemonBanner>
            ) : null}
            {totals && usageRows.length > 0 ? (
                <div className="text-secondary text-sm">
                    Across all environments: {formatBytes(totals.log_bytes)} of logs,{' '}
                    {humanFriendlyNumber(totals.spans)} spans, and {humanFriendlyNumber(totals.metric_points)} metric
                    points from {humanFriendlyNumber(totals.metric_series)} series.
                </div>
            ) : null}
            <LemonTable
                columns={columns}
                dataSource={usageRows}
                rowKey="service_name"
                loading={serviceUsageLoading}
                emptyState={
                    usageLoadError
                        ? "Couldn't load usage. Check your connection and try again."
                        : 'No logs, spans, or metrics in this time range. Send telemetry from your services to see their usage here.'
                }
                pagination={{ pageSize: 50 }}
                data-attr="apm-usage-table"
            />
        </div>
    )
}

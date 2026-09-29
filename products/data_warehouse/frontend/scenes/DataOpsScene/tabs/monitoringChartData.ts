import type { Series } from '@posthog/quill-charts'

import type {
    DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveParams,
    ManagedWarehouseMonitoringSeriesResponseApi,
} from 'products/data_warehouse/frontend/generated/api.schemas'

export type MonitoringChartMetric = NonNullable<
    DataWarehouseManagedWarehouseMonitoringTimeseriesRetrieveParams['metric']
>
type MonitoringSeries = ManagedWarehouseMonitoringSeriesResponseApi['series'][number]

export interface MonitoringChartMetricConfig {
    metric: MonitoringChartMetric
    fallbackLabel: string
}

function sentenceCase(value: string): string {
    const normalized = value.replaceAll('_', ' ')
    return normalized.charAt(0).toUpperCase() + normalized.slice(1)
}

function sortedLabels(series: MonitoringSeries): [string, string][] {
    return Object.entries(series.labels).sort(([left], [right]) => left.localeCompare(right))
}

function seriesLabel(series: MonitoringSeries, fallback: string): string {
    const labels = sortedLabels(series)
    if (!labels.length) {
        return fallback
    }
    if (labels.length === 1) {
        return sentenceCase(labels[0][1])
    }
    return labels.map(([key, value]) => `${sentenceCase(key)}: ${value}`).join(', ')
}

export function buildMonitoringChartData(
    responses: ManagedWarehouseMonitoringSeriesResponseApi[],
    metrics: MonitoringChartMetricConfig[]
): { labels: string[]; series: Series[] } {
    const chartResponses = metrics.flatMap(({ metric }) => {
        const response = responses.find((candidate) => candidate.metric === metric)
        return response ? [response] : []
    })
    const stepMilliseconds = Math.max(1, ...chartResponses.map((response) => response.step_seconds)) * 1000
    const configuredSeries = metrics
        .flatMap(({ metric, fallbackLabel }) => {
            const response = chartResponses.find((candidate) => candidate.metric === metric)
            return (response?.series ?? []).map((series) => ({
                key: `${metric}:${JSON.stringify(sortedLabels(series))}`,
                label: seriesLabel(series, fallbackLabel),
                points: new Map(
                    series.points.map((point) => [
                        new Date(
                            Math.round(new Date(point.timestamp).getTime() / stepMilliseconds) * stepMilliseconds
                        ).toISOString(),
                        point.value,
                    ])
                ),
            }))
        })
        .sort((left, right) => left.key.localeCompare(right.key))

    if (!configuredSeries.length) {
        return { labels: [], series: [] }
    }

    const labels = [...new Set(configuredSeries.flatMap(({ points }) => [...points.keys()]))].sort()

    return {
        labels,
        series: configuredSeries.map(({ key, label, points }) => ({
            key,
            label,
            data: labels.map((timestamp) => points.get(timestamp) ?? Number.NaN),
        })),
    }
}

import { useMemo } from 'react'

import { type Series, TimeSeriesLineChart, type TimeSeriesLineChartConfig } from '@posthog/quill-charts'

import { useChartConfig, useChartTheme } from 'lib/charts/hooks'

import type { TraceMetricBucketSizeApi, TraceMetricKeyApi } from '../../../generated/api.schemas'
import { formatTileValue } from '../formatTile'

export interface KpiTileChartProps {
    metricKey: TraceMetricKeyApi
    label: string
    series: (number | null)[]
    bucketStarts: string[]
    bucketSize: TraceMetricBucketSizeApi
    timezone: string
}

export function KpiTileChart({
    metricKey,
    label,
    series,
    bucketStarts,
    bucketSize,
    timezone,
}: KpiTileChartProps): JSX.Element {
    const theme = useChartTheme()
    const chartSeries = useMemo<Series[]>(
        () => [{ key: metricKey, label, data: series.map((value) => value ?? NaN) }],
        [metricKey, label, series]
    )
    const config = useChartConfig<TimeSeriesLineChartConfig>(() => {
        const format = (value: number): string => formatTileValue(metricKey, value)
        return {
            xAxis: { timezone, interval: bucketSize },
            yAxis: { tickFormatter: format, showGrid: true },
            tooltip: { valueFormatter: format },
        }
    }, [metricKey, timezone, bucketSize])
    return <TimeSeriesLineChart series={chartSeries} labels={bucketStarts} theme={theme} config={config} />
}

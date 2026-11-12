import { useActions, useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'
import {
    DefaultTooltip,
    type Series,
    TimeSeriesBarChart,
    type TimeSeriesBarChartConfig,
    type TooltipContext,
    createTooltipDateFormatter,
} from '@posthog/quill-charts'

import { makeChartErrorHandler } from 'lib/charts/chartErrorHandler'
import { useChartConfig, useChartTheme } from 'lib/charts/hooks'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { HogQLQueryResponse } from '~/queries/schema/schema-general'

import { aiObservabilityMetricChartLogic } from './aiObservabilityMetricChartLogic'
import { METRIC_CHART_DEFINITIONS, MetricChartKey } from './metricChart'

const handleChartError = makeChartErrorHandler('ai-observability-metric-chart')

const METRIC_OPTIONS = (Object.keys(METRIC_CHART_DEFINITIONS) as MetricChartKey[]).map((key) => ({
    value: key,
    label: METRIC_CHART_DEFINITIONS[key].label,
}))

export interface AIObservabilityMetricChartProps {
    metric?: MetricChartKey
    /** A plain HogQL query can't read the content the table searches. */
    searchApplied?: boolean
    /** The data-node collection its table's Reload refreshes. */
    collectionId: string
}

export function AIObservabilityMetricChart({
    metric: pinnedMetric,
    searchApplied,
    collectionId,
}: AIObservabilityMetricChartProps): JSX.Element {
    const logic = aiObservabilityMetricChartLogic({ metric: pinnedMetric })
    const { activeMetric: metric, interval, canZoom, query, bucketTraceLoading } = useValues(logic)
    const { setMetric, zoomTo, openBucketTrace } = useActions(logic)
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const { response, responseLoading, responseError } = useValues(
        dataNodeLogic({
            key: `ai-observability-metric-chart-${pinnedMetric ?? 'pickable'}`,
            query,
            dataNodeCollectionId: collectionId,
        })
    )

    const definition = METRIC_CHART_DEFINITIONS[metric]
    const rows = (response as HogQLQueryResponse | null)?.results as [string, number | null, number][] | undefined
    const labels = useMemo<string[]>(() => rows?.map(([label]) => label) ?? [], [rows])
    const traceCounts = useMemo(() => rows?.map(([, , traces]) => traces), [rows])
    const series = useMemo<Series[]>(
        // An empty bucket has no average latency; it draws as zero.
        () => [{ key: metric, label: definition.label, data: rows?.map(([, value]) => value ?? 0) ?? [] }],
        [metric, definition, rows]
    )
    const config = useChartConfig<TimeSeriesBarChartConfig>(
        () => ({
            barCornerRadius: 2,
            showGrid: true,
            xAxis: { timezone, interval },
            yAxis: { startAtZero: true, tickFormatter: definition.format },
            tooltip: { placement: 'cursor', valueFormatter: definition.format },
        }),
        [timezone, interval, definition]
    )
    // Past the smallest bucket there is nothing to zoom into, so a bar holding one trace opens it instead.
    // One lookup at a time, so repeated clicks on a slow bar don't stack queries.
    const opensTrace = useCallback(
        (index: number) => !canZoom && !bucketTraceLoading && traceCounts?.[index] === 1,
        [canZoom, bucketTraceLoading, traceCounts]
    )
    const labelFormatter = useMemo(
        () => createTooltipDateFormatter({ interval, timezone, allDays: labels }),
        [interval, timezone, labels]
    )
    const renderTooltip = useCallback(
        (ctx: TooltipContext) => {
            const clickHint = canZoom
                ? 'Click to zoom in'
                : bucketTraceLoading
                  ? 'Opening the trace…'
                  : opensTrace(ctx.dataIndex)
                    ? 'Click to open the trace'
                    : null
            return (
                <DefaultTooltip
                    {...ctx}
                    labelFormatter={labelFormatter}
                    valueFormatter={definition.format}
                    footer={clickHint ?? undefined}
                />
            )
        },
        [labelFormatter, definition, canZoom, bucketTraceLoading, opensTrace]
    )
    const isPointClickable = useCallback((index: number) => canZoom || opensTrace(index), [canZoom, opensTrace])
    const onPointClick = useCallback(
        ({ label, dataIndex }: { label: string; dataIndex: number }) =>
            canZoom
                ? zoomTo(label, labels[dataIndex + 1] ?? null)
                : opensTrace(dataIndex) && openBucketTrace({ label }),
        [canZoom, zoomTo, opensTrace, openBucketTrace, labels]
    )
    const onDateRangeZoom = useCallback(
        ({ startLabel, endLabel }: { startLabel: string; endLabel: string }) =>
            zoomTo(startLabel, labels[labels.indexOf(endLabel) + 1] ?? null),
        [zoomTo, labels]
    )

    return (
        <div
            className="border rounded bg-surface-primary p-2 flex flex-col gap-2"
            data-attr="ai-observability-metric-chart"
        >
            <div className="flex flex-wrap items-center gap-2">
                {pinnedMetric ? (
                    <span className="text-sm font-semibold">{definition.label}</span>
                ) : (
                    <LemonSelect
                        size="small"
                        value={metric}
                        onChange={setMetric}
                        options={METRIC_OPTIONS}
                        data-attr="ai-observability-metric-chart-select"
                    />
                )}
                {searchApplied && (
                    <span className="text-xs text-secondary">The chart doesn't apply the content search.</span>
                )}
            </div>
            <div className="h-40 flex flex-col">
                {responseLoading ? (
                    <LemonSkeleton className="h-full w-full" />
                ) : responseError ? (
                    <div className="h-full flex items-center justify-center text-secondary text-sm">
                        Couldn't load this chart. Reload to try again.
                    </div>
                ) : (
                    <TimeSeriesBarChart
                        series={series}
                        labels={labels}
                        theme={theme}
                        config={config}
                        tooltip={renderTooltip}
                        isPointClickable={isPointClickable}
                        onPointClick={onPointClick}
                        onDateRangeZoom={canZoom ? onDateRangeZoom : undefined}
                        onError={handleChartError}
                    />
                )}
            </div>
        </div>
    )
}

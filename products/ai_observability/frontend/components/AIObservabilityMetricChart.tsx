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
import { TrendsQueryResponse } from '~/queries/schema/schema-general'

import { AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID } from '../aiObservabilitySharedLogic'
import { aiObservabilityMetricChartLogic } from './aiObservabilityMetricChartLogic'
import { METRIC_CHART_DEFINITIONS, MetricChartKey } from './metricChart'

const handleChartError = makeChartErrorHandler('ai-observability-metric-chart')

const METRIC_OPTIONS = (Object.keys(METRIC_CHART_DEFINITIONS) as MetricChartKey[]).map((key) => ({
    value: key,
    label: METRIC_CHART_DEFINITIONS[key].label,
}))

export function AIObservabilityMetricChart({ metric: pinnedMetric }: { metric?: MetricChartKey }): JSX.Element {
    const logic = aiObservabilityMetricChartLogic({ metric: pinnedMetric })
    const { activeMetric: metric, interval, canZoom, query } = useValues(logic)
    const { setMetric, zoomTo, openBucketTrace } = useActions(logic)
    const { timezone } = useValues(teamLogic)
    const theme = useChartTheme()
    const { response, responseLoading, responseError } = useValues(
        dataNodeLogic({
            key: `ai-observability-metric-chart-${pinnedMetric ?? 'pickable'}`,
            query,
            dataNodeCollectionId: AI_OBSERVABILITY_DATA_COLLECTION_NODE_ID,
        })
    )

    const definition = METRIC_CHART_DEFINITIONS[metric]
    const [result, traces] = (response as TrendsQueryResponse | null)?.results ?? []
    const traceCounts: number[] | undefined = traces?.data
    const labels = useMemo<string[]>(() => result?.days ?? [], [result])
    const series = useMemo<Series[]>(
        () => [{ key: metric, label: definition.label, data: result?.data ?? [] }],
        [metric, definition, result]
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
    const opensTrace = useCallback((index: number) => !canZoom && traceCounts?.[index] === 1, [canZoom, traceCounts])
    const labelFormatter = useMemo(
        () => createTooltipDateFormatter({ interval, timezone, allDays: labels }),
        [interval, timezone, labels]
    )
    const renderTooltip = useCallback(
        (ctx: TooltipContext) => {
            const clickHint = canZoom
                ? 'Click to zoom in'
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
        [labelFormatter, definition, canZoom, opensTrace]
    )
    const isPointClickable = useCallback((index: number) => canZoom || opensTrace(index), [canZoom, opensTrace])
    const onPointClick = useCallback(
        ({ label, dataIndex }: { label: string; dataIndex: number }) =>
            canZoom ? zoomTo(label, label) : opensTrace(dataIndex) && openBucketTrace(label),
        [canZoom, zoomTo, opensTrace, openBucketTrace]
    )
    const onDateRangeZoom = useCallback(
        ({ startLabel, endLabel }: { startLabel: string; endLabel: string }) => zoomTo(startLabel, endLabel),
        [zoomTo]
    )

    return (
        <div
            className="border rounded bg-surface-primary p-2 flex flex-col gap-2"
            data-attr="ai-observability-metric-chart"
        >
            {pinnedMetric ? (
                <span className="text-sm font-semibold">{definition.label}</span>
            ) : (
                <LemonSelect
                    size="small"
                    value={metric}
                    onChange={setMetric}
                    options={METRIC_OPTIONS}
                    className="self-start"
                    data-attr="ai-observability-metric-chart-select"
                />
            )}
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

import { useActions, useValues } from 'kea'
import { type ReactNode, useState } from 'react'

import { IconClock } from '@posthog/icons'
import { Card, CardContent, Collapsible, CollapsibleContent, CollapsibleTrigger, Skeleton, Text } from '@posthog/quill'

import { getMetricRecordingModes } from 'scenes/experiments/ExperimentView/experimentRecordingModes'
import { QuillMetricBreakdowns } from 'scenes/experiments/MetricBreakdowns/QuillMetricBreakdowns'
import { viewRecordingsLinkabilityLogic } from 'scenes/experiments/viewRecordingsLinkabilityLogic'
import { formatBreakdownLabel } from 'scenes/insights/utils'

import {
    ExperimentMetric,
    ExperimentStatsBaseValidated,
    NewExperimentQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { experimentMetricsLogic } from '~/scenes/experiments/experimentMetricsLogic'
import { MetricHeader } from '~/scenes/experiments/MetricsView/shared/MetricHeader'
import { MetricRetryState } from '~/scenes/experiments/MetricsView/shared/MetricRetryState'
import { type ExperimentVariantResult } from '~/scenes/experiments/MetricsView/shared/utils'
import { Experiment, ExperimentStatsMethod } from '~/types'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'
import { DetailsModal } from 'products/experiments/frontend/modals/DetailsModal/DetailsModal'
import { TimeseriesModal } from 'products/experiments/frontend/modals/TimeseriesModal/TimeseriesModal'

import { QuillMetricErrorState } from './QuillMetricErrorState'
import { QuillVariantActionsMenu } from './QuillVariantActionsMenu'
import { QuillVariantResultsTable, type VariantRow } from './QuillVariantResultsTable'
import { type MetricHandlers } from './useMetricsTableModel'

function variantRows(baseline: ExperimentStatsBaseValidated, variants: ExperimentVariantResult[]): VariantRow[] {
    return [
        { variant: baseline, isBaseline: true },
        ...variants.map((variant): VariantRow => ({ variant, isBaseline: false })),
    ]
}

function ResultsSkeleton({ rows }: { rows: number }): JSX.Element {
    return (
        <div className="flex flex-col gap-2 px-3 pb-3">
            {Array.from({ length: rows }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
            ))}
        </div>
    )
}

export function QuillMetricCard({
    metric,
    result,
    error,
    experiment,
    axisRange,
    isSecondary,
    statsMethod,
    sequentialTestingEnabled,
    dragHandle,
    isLoading,
    exposuresLoading,
    showDetailsModal,
    footer,
    onDuplicateMetric,
    onDuplicateAsSingleUseMetric,
    onDeleteMetric,
    onBreakdownChange,
    onRemoveBreakdown,
    onBreakdownAttributionChange,
    onBreakdownLimitChange,
}: MetricHandlers & {
    metric: ExperimentMetric
    result: NewExperimentQueryResponse | null
    error?: any
    experiment: Experiment
    axisRange: number
    isSecondary: boolean
    statsMethod: ExperimentStatsMethod
    sequentialTestingEnabled: boolean
    dragHandle?: JSX.Element | null
    isLoading: boolean
    exposuresLoading: boolean
    showDetailsModal: boolean
    footer?: ReactNode
}): JSX.Element {
    const [detailsOpen, setDetailsOpen] = useState(false)
    const [timeseriesVariant, setTimeseriesVariant] = useState<ExperimentVariantResult | null>(null)

    const { variants } = useValues(experimentLogic)
    const { reportExperimentTimeseriesViewed, refreshExperimentResults } = useActions(experimentLogic)
    const { isRecalculating, metricRetries } = useValues(experimentMetricsLogic({ experiment }))
    const { triggerRecalculation } = useActions(experimentMetricsLogic({ experiment }))
    const { unlinkableEventNames, linkabilityLoaded } = useValues(viewRecordingsLinkabilityLogic({ experiment }))
    const recordingModes = getMetricRecordingModes(metric, linkabilityLoaded ? unlinkableEventNames : new Set<string>())

    const debugQuery = { kind: NodeKind.ExperimentQuery, metric, experiment_id: experiment.id }
    const hasBreakdowns = (metric.breakdownFilter?.breakdowns?.length ?? 0) > 0
    const metricRetry = metric.uuid ? metricRetries[metric.uuid] : undefined
    const retryDisabledReason = isRecalculating ? 'Recalculation in progress' : undefined

    const handleRetry = (): void => {
        triggerRecalculation('manual_retry')
        refreshExperimentResults(true, 'manual')
    }

    const openTimeseries = (variant: ExperimentVariantResult): void => {
        setTimeseriesVariant(variant)
        reportExperimentTimeseriesViewed(experiment.id, metric)
    }

    const breakdownControls = hasBreakdowns ? (
        <QuillMetricBreakdowns
            metric={metric}
            onRemoveBreakdown={onRemoveBreakdown}
            onAttributionChange={onBreakdownAttributionChange}
            onBreakdownLimitChange={onBreakdownLimitChange}
        />
    ) : null

    const resultsTable = (rows: VariantRow[], gradientSuffix?: string): JSX.Element => (
        <QuillVariantResultsTable
            metric={metric}
            rows={rows}
            axisRange={axisRange}
            isSecondary={isSecondary}
            statsMethod={statsMethod}
            sequentialTestingEnabled={sequentialTestingEnabled}
            onTimeseriesClick={openTimeseries}
            gradientSuffix={gradientSuffix}
            variantActions={
                result
                    ? (row) => (
                          <QuillVariantActionsMenu
                              experiment={experiment}
                              metric={metric}
                              variantKey={row.variant.key}
                              isBaseline={row.isBaseline}
                              modes={recordingModes}
                              hogql={result.hogql}
                              clickhouseSql={result.clickhouse_sql}
                          />
                      )
                    : undefined
            }
        />
    )

    let body: ReactNode
    if (!result && !error && (isLoading || exposuresLoading)) {
        body = metricRetry ? (
            <div className="px-3 pb-3">
                <MetricRetryState retry={metricRetry} />
            </div>
        ) : (
            <ResultsSkeleton rows={Math.max(variants.length, 1)} />
        )
    } else if (error) {
        body = (
            <QuillMetricErrorState
                error={error}
                query={debugQuery}
                onRetry={error?.retriable === true ? handleRetry : undefined}
                retryDisabledReason={retryDisabledReason}
            />
        )
    } else if (!result) {
        body = isLaunched(experiment) ? null : (
            <div className="flex items-center justify-center gap-2 px-3 pb-4">
                <IconClock className="text-muted-foreground" />
                <Text size="xs" variant="muted" render={<span />}>
                    Waiting for experiment to start&hellip;
                </Text>
            </div>
        )
    } else {
        body = resultsTable(variantRows(result.baseline, result.variant_results || []))
    }

    const breakdownResults = result?.breakdown_results ?? []
    const breakdownsExpandable = !!result && !isRecalculating && breakdownResults.length > 0

    return (
        <Card size="sm" flush className="group/metric-cell" data-attr="experiment-metric-card">
            <CardContent className="flex flex-col gap-3">
                <div className="px-3">
                    <MetricHeader
                        dragHandle={dragHandle}
                        metric={metric}
                        isPrimaryMetric={!isSecondary}
                        experiment={experiment}
                        onDuplicateMetricClick={() => onDuplicateMetric?.()}
                        onDuplicateAsSingleUseMetricClick={() => onDuplicateAsSingleUseMetric?.()}
                        onDeleteMetricClick={onDeleteMetric ? () => onDeleteMetric() : undefined}
                        onBreakdownChange={onBreakdownChange}
                        onViewDetailsClick={result && showDetailsModal ? () => setDetailsOpen(true) : undefined}
                    />
                </div>
                {body}
                {hasBreakdowns && (
                    <div className="border-t border-border px-3 pt-3">
                        {breakdownsExpandable ? (
                            <Collapsible variant="folder" className="flex flex-col gap-2 pb-2">
                                {breakdownControls}
                                <CollapsibleTrigger className="-ml-2" data-attr="experiment-breakdown-toggle">
                                    Breakdown results
                                </CollapsibleTrigger>
                                <CollapsibleContent className="-mx-3 flex flex-col gap-3 px-0 pb-0">
                                    {breakdownResults.map((breakdownResult) => (
                                        <div
                                            key={JSON.stringify(breakdownResult.breakdown_value)}
                                            className="flex flex-col gap-1"
                                        >
                                            <Text size="xs" weight="semibold" render={<span className="px-3" />}>
                                                {formatBreakdownLabel(
                                                    breakdownResult.breakdown_value,
                                                    metric.breakdownFilter,
                                                    [],
                                                    undefined,
                                                    0,
                                                    undefined
                                                )}
                                            </Text>
                                            {(breakdownResult.variants?.length ?? 0) > 0 ? (
                                                resultsTable(
                                                    variantRows(breakdownResult.baseline, breakdownResult.variants),
                                                    `-${breakdownResult.breakdown_value.join('-')}`
                                                )
                                            ) : isLoading || exposuresLoading ? (
                                                <div className="px-3">
                                                    <Skeleton className="h-10 w-full" />
                                                </div>
                                            ) : null}
                                        </div>
                                    ))}
                                </CollapsibleContent>
                            </Collapsible>
                        ) : (
                            <div className="pb-3">{breakdownControls}</div>
                        )}
                    </div>
                )}
                {footer && <div className="border-t border-border">{footer}</div>}
            </CardContent>
            {result && showDetailsModal && (
                <DetailsModal
                    isOpen={detailsOpen}
                    onClose={() => setDetailsOpen(false)}
                    metric={metric}
                    result={result}
                    experiment={experiment}
                />
            )}
            {timeseriesVariant && (
                <TimeseriesModal
                    isOpen
                    onClose={() => setTimeseriesVariant(null)}
                    metric={metric}
                    variantResult={timeseriesVariant}
                    experiment={experiment}
                />
            )}
        </Card>
    )
}

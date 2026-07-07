import posthog from 'posthog-js'
import { useState } from 'react'

import { HedgehogExperiment } from '@posthog/brand/hoggies'
import { LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { urls } from 'scenes/urls'

import type { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import type { ExperimentStatus } from '~/types'

import { WidgetCardBodyMessage, WidgetCardContent } from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import { ExperimentPickerSelect } from './ExperimentPickerSelect'
import { patchExperimentResultsWidgetConfig } from './experimentsWidgetConfigValidation'
import { NotebookCompactTable } from './LazyNotebookCompactTable'

export type ExperimentResultsWidgetMetricEntry = {
    uuid: string | null
    name: string
    metric: ExperimentMetric | null
    result: NewExperimentQueryResponse | null
    error: string | null
}

export type ExperimentResultsWidgetResult = {
    experiment: {
        id: number
        name: string
        status: string
        start_date: string | null
        end_date: string | null
        feature_flag_key: string
    } | null
    metrics: ExperimentResultsWidgetMetricEntry[]
    secondaryMetrics?: ExperimentResultsWidgetMetricEntry[]
    needsConfiguration?: boolean
    experimentNotFound?: boolean
    hasExperiments?: boolean
    totalMetricsCount?: number
    totalSecondaryMetricsCount?: number
}

// Sample count of the first primary metric that has results (baseline + every variant). This is that
// metric's analysis population, not a canonical exposure count — metrics with custom exposure criteria
// can differ. We read it off primary only so the headline doesn't silently come from a secondary metric.
function getPrimarySampleCount(metrics: ExperimentResultsWidgetMetricEntry[]): number | null {
    for (const entry of metrics) {
        const variantResults = entry.result?.variant_results
        if (!variantResults?.length) {
            continue
        }
        let total = entry.result?.baseline?.number_of_samples ?? 0
        for (const variant of variantResults) {
            total += variant.number_of_samples ?? 0
        }
        return total
    }
    return null
}

function ExperimentResultsWidgetMessage({
    title,
    message,
    cta,
}: {
    title: string
    message: string
    cta?: JSX.Element
}): JSX.Element {
    return (
        <WidgetCardContent>
            <WidgetCardBodyMessage>
                <div
                    className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                    data-attr="experiment-results-widget-message"
                >
                    <HedgehogExperiment className="size-20 shrink-0" />
                    <p className="m-0 text-base font-semibold text-primary">{title}</p>
                    <p className="m-0 text-sm text-muted">{message}</p>
                    {cta}
                </div>
            </WidgetCardBodyMessage>
        </WidgetCardContent>
    )
}

function ExperimentResultsWidgetMetric({ entry }: { entry: ExperimentResultsWidgetMetricEntry }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <h6 className="m-0 text-xs font-semibold text-muted">{entry.name}</h6>
            {entry.error || !entry.metric || !entry.result ? (
                <LemonBanner type="info" className="text-sm">
                    {entry.error ?? 'No results available for this metric yet.'}
                </LemonBanner>
            ) : (
                <NotebookCompactTable result={entry.result} metric={entry.metric} />
            )}
        </div>
    )
}

function ExperimentMetricsSection({
    label,
    metrics,
    totalCount,
    emptyMessage,
}: {
    label: string
    metrics: ExperimentResultsWidgetMetricEntry[]
    totalCount?: number
    emptyMessage?: string
}): JSX.Element {
    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
                <h5 className="m-0 shrink-0 text-xs font-semibold uppercase tracking-wide text-muted">{label}</h5>
                <LemonDivider className="my-0 flex-1" />
            </div>
            {metrics.length === 0 ? (
                <LemonBanner type="info" className="text-sm">
                    {emptyMessage}
                </LemonBanner>
            ) : (
                metrics.map((entry, index) => <ExperimentResultsWidgetMetric key={entry.uuid ?? index} entry={entry} />)
            )}
            {totalCount != null && totalCount > metrics.length ? (
                <span className="text-xs text-muted">
                    Showing the first {metrics.length} of {totalCount} {label.toLowerCase()}. Open the experiment to see
                    all of them.
                </span>
            ) : null}
        </div>
    )
}

function ExperimentResultsLoadingSkeleton(): JSX.Element {
    return (
        <WidgetCardContent>
            <div className="flex flex-col gap-3 p-2" aria-busy aria-label="Loading experiment results">
                <div className="flex items-center justify-between gap-2" aria-hidden>
                    <LemonSkeleton className="h-4 w-1/3 max-w-xs" />
                    <LemonSkeleton className="h-5 w-20 rounded" />
                </div>
                <div className="flex flex-col gap-2" aria-hidden>
                    <LemonSkeleton className="h-3 w-24" />
                    <div className="flex flex-col gap-2 rounded border p-2">
                        {Array.from({ length: 3 }, (_, index) => (
                            <div key={index} className="flex items-center justify-between gap-4">
                                <LemonSkeleton className="h-3 w-1/4" />
                                <LemonSkeleton className="h-3 w-1/5" />
                                <LemonSkeleton className="h-3 w-1/6" />
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </WidgetCardContent>
    )
}

export function ExperimentResultsWidget({
    tileId,
    config,
    result,
    loading,
    onUpdateConfig,
}: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as ExperimentResultsWidgetResult | null | undefined

    // Reflect the empty-state pick immediately rather than waiting for the persist + refresh round-trip.
    const [optimisticExperimentId, setOptimisticExperimentId] = useState<number | null>(null)

    if (loading) {
        return <ExperimentResultsLoadingSkeleton />
    }

    if (!payload || payload.needsConfiguration) {
        // No experiments in the project yet — mirror the list widget's "create one" CTA.
        if (onUpdateConfig && payload && payload.hasExperiments === false) {
            return (
                <ExperimentResultsWidgetMessage
                    title="No experiments yet"
                    message="Run A/B tests to measure the impact of changes on your product."
                    cta={
                        <LemonButton
                            type="primary"
                            size="small"
                            to={urls.experiment('new')}
                            targetBlank
                            onClick={() =>
                                posthog.capture('dashboard widget create experiment clicked', {
                                    widget_type: 'experiment_results',
                                    tile_id: tileId,
                                })
                            }
                        >
                            New experiment
                        </LemonButton>
                    }
                />
            )
        }
        // Editable tile, no experiment chosen yet — let the user pick one inline (shares the tile picker's key).
        const inlinePicker = onUpdateConfig ? (
            <div className="w-64 max-w-full">
                <ExperimentPickerSelect
                    pickerKey={`results-tile-${tileId}`}
                    value={optimisticExperimentId}
                    fullWidth
                    onChange={async (value) => {
                        setOptimisticExperimentId(value)
                        try {
                            await onUpdateConfig(patchExperimentResultsWidgetConfig(config, value))
                        } catch {
                            // Persist failed — drop the optimistic pick so we don't show a selection that wasn't saved.
                            setOptimisticExperimentId((current) => (current === value ? null : current))
                        }
                    }}
                    dataAttr="experiment-results-widget-empty-state-select"
                />
            </div>
        ) : undefined
        return (
            <ExperimentResultsWidgetMessage
                title="No experiment selected"
                message={
                    onUpdateConfig
                        ? 'Pick an experiment to see its results here.'
                        : 'No experiment has been selected for this tile yet.'
                }
                cta={inlinePicker}
            />
        )
    }

    if (payload.experimentNotFound || !payload.experiment) {
        return (
            <ExperimentResultsWidgetMessage
                title="Experiment not found"
                message="This experiment may have been deleted. Pick another one in the widget settings."
            />
        )
    }

    const { experiment, metrics } = payload
    const secondaryMetrics = payload.secondaryMetrics ?? []
    const isDraft = experiment.status === 'draft'
    const primarySampleCount = getPrimarySampleCount(metrics)

    return (
        <WidgetCardContent>
            <div className="flex flex-col gap-3 p-2" data-attr="experiment-results-widget-body">
                <div className="flex items-center justify-between gap-2">
                    {/* The experiment name already shows in the tile filter bar, so link out rather than repeat it. */}
                    <Link
                        to={urls.experiment(experiment.id)}
                        target="_blank"
                        className="text-sm font-medium"
                        onClick={() =>
                            posthog.capture('dashboard widget open experiment clicked', {
                                widget_type: 'experiment_results',
                                tile_id: tileId,
                                experiment_id: experiment.id,
                            })
                        }
                    >
                        See more
                    </Link>
                    <StatusTag status={experiment.status as ExperimentStatus} />
                </div>
                {primarySampleCount != null ? (
                    <span className="text-xs text-muted">
                        {humanFriendlyNumber(primarySampleCount)} total exposures
                    </span>
                ) : null}
                {isDraft ? (
                    <LemonBanner type="info" className="text-sm">
                        This experiment has not launched yet. Results will appear once it is running.
                    </LemonBanner>
                ) : (
                    <>
                        <ExperimentMetricsSection
                            label="Primary metrics"
                            metrics={metrics}
                            totalCount={payload.totalMetricsCount}
                            emptyMessage="This experiment has no primary metrics to show."
                        />
                        {secondaryMetrics.length > 0 ? (
                            <ExperimentMetricsSection
                                label="Secondary metrics"
                                metrics={secondaryMetrics}
                                totalCount={payload.totalSecondaryMetricsCount}
                            />
                        ) : null}
                    </>
                )}
            </div>
        </WidgetCardContent>
    )
}

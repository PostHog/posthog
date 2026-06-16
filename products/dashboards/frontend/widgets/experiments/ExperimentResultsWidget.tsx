import { LemonSkeleton } from '@posthog/lemon-ui'

import { ExperimentsHog } from 'lib/components/hedgehogs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Link } from 'lib/lemon-ui/Link'
import { StatusTag } from 'scenes/experiments/ExperimentView/StatusTag'
import { NotebookCompactTable } from 'scenes/experiments/notebook/NotebookCompactTable'
import { urls } from 'scenes/urls'

import type { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import type { ExperimentStatus } from '~/types'

import { WidgetCardBodyMessage, WidgetCardContent } from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'

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
    needsConfiguration?: boolean
    experimentNotFound?: boolean
    totalMetricsCount?: number
}

function ExperimentResultsWidgetMessage({ title, message }: { title: string; message: string }): JSX.Element {
    return (
        <WidgetCardContent>
            <WidgetCardBodyMessage>
                <div
                    className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                    data-attr="experiment-results-widget-message"
                >
                    <ExperimentsHog className="size-20 shrink-0" />
                    <p className="m-0 text-base font-semibold text-primary">{title}</p>
                    <p className="m-0 text-sm text-muted">{message}</p>
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
    result,
    loading,
    onUpdateConfig,
}: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as ExperimentResultsWidgetResult | null | undefined

    if (loading) {
        return <ExperimentResultsLoadingSkeleton />
    }

    if (!payload || payload.needsConfiguration) {
        return (
            <ExperimentResultsWidgetMessage
                title="No experiment selected"
                message={
                    onUpdateConfig
                        ? 'Pick an experiment from the selector above to see its results here.'
                        : 'No experiment has been selected for this tile yet.'
                }
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
    const isDraft = experiment.status === 'draft'

    return (
        <WidgetCardContent>
            <div className="flex flex-col gap-3 p-2" data-attr="experiment-results-widget-body">
                <div className="flex items-center justify-between gap-2">
                    <Link
                        to={urls.experiment(experiment.id)}
                        target="_blank"
                        className="truncate font-semibold text-primary"
                        title={experiment.name}
                    >
                        {experiment.name}
                    </Link>
                    <StatusTag status={experiment.status as ExperimentStatus} />
                </div>
                {isDraft ? (
                    <LemonBanner type="info" className="text-sm">
                        This experiment has not launched yet. Results will appear once it is running.
                    </LemonBanner>
                ) : metrics.length === 0 ? (
                    <LemonBanner type="info" className="text-sm">
                        This experiment has no primary metrics to show.
                    </LemonBanner>
                ) : (
                    metrics.map((entry, index) => (
                        <ExperimentResultsWidgetMetric key={entry.uuid ?? index} entry={entry} />
                    ))
                )}
                {payload.totalMetricsCount && payload.totalMetricsCount > metrics.length ? (
                    <span className="text-xs text-muted">
                        Showing the first {metrics.length} of {payload.totalMetricsCount} primary metrics. Open the
                        experiment to see all of them.
                    </span>
                ) : null}
            </div>
        </WidgetCardContent>
    )
}

import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconFlask } from '@posthog/icons'
import { LemonBanner, LemonDivider, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { dayjs } from 'lib/dayjs'
import { humanFriendlyDiff } from 'lib/utils/durations'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import {
    CachedNewExperimentQueryResponse,
    ExperimentExposureQueryResponse,
    ExperimentMetric,
} from '~/queries/schema/schema-general'
import { ResultsTag } from '~/scenes/experiments/components/ResultsTag'
import { experimentLogic } from '~/scenes/experiments/experimentLogic'
import { getExperimentStatus } from '~/scenes/experiments/experimentsLogic'
import { MicroChart } from '~/scenes/experiments/ExperimentView/Exposures'
import { StatusTag } from '~/scenes/experiments/ExperimentView/StatusTag'
import { getChanceToWin, isBayesianResult } from '~/scenes/experiments/MetricsView/shared/utils'
import { isLegacyExperiment } from '~/scenes/experiments/utils'

import { ExperimentStatItem } from './ExperimentStatItem'
import { NotebookCompactTable } from './NotebookCompactTable'
import { NotebookWinningVariantSummary } from './NotebookWinningVariantSummary'

export interface NotebookExperimentComponentProps {
    id: number
    expanded: boolean
}

function formatDuration(startDate: string | null | undefined, endDate: string | null | undefined): string {
    if (!startDate) {
        return 'Not started'
    }
    const start = dayjs(startDate)
    const end = endDate ? dayjs(endDate) : dayjs()
    return humanFriendlyDiff(start, end)
}

function formatTotalExposures(exposures: ExperimentExposureQueryResponse | null): string {
    if (!exposures?.total_exposures) {
        return '0'
    }
    const total = Object.values(exposures.total_exposures).reduce((a, b) => a + b, 0)
    return humanFriendlyNumber(total)
}

interface MetricWithResult {
    metric: ExperimentMetric
    result: CachedNewExperimentQueryResponse
    index: number
    maxChanceToWin: number
    isSignificant: boolean
}

function findMostSignificantMetric(
    metrics: ExperimentMetric[] | undefined,
    results: CachedNewExperimentQueryResponse[] | undefined
): MetricWithResult | null {
    if (!metrics?.length || !results?.length) {
        return null
    }

    const metricsWithResults = metrics
        .map((metric, index) => {
            const result = results[index]
            if (!result?.variant_results?.length) {
                return null
            }

            const goal = 'goal' in metric ? metric.goal : undefined
            const isSignificant = result.variant_results.some((v) => v.significant)
            const maxChanceToWin = result.variant_results
                .filter(isBayesianResult)
                .map((v) => getChanceToWin(v, goal) ?? 0)
                .reduce((max, ctw) => Math.max(max, ctw), 0)

            return { metric, result, index, maxChanceToWin, isSignificant }
        })
        .filter((m): m is MetricWithResult => m !== null)

    if (metricsWithResults.length === 0) {
        return null
    }

    return metricsWithResults.reduce((best, current) => {
        if (current.isSignificant && !best.isSignificant) {
            return current
        }
        if (current.isSignificant === best.isSignificant && current.maxChanceToWin > best.maxChanceToWin) {
            return current
        }
        return best
    })
}

export function NotebookExperimentComponent({ id, expanded }: NotebookExperimentComponentProps): JSX.Element {
    const {
        experiment,
        experimentLoading,
        experimentMissing,
        isExperimentDraft,
        isExperimentLaunched,
        primaryMetricsResults,
        primaryMetricsResultsLoading,
        exposures,
        exposuresLoading,
        variants,
    } = useValues(experimentLogic({ experimentId: id }))

    const { loadExperiment, loadExposures } = useActions(experimentLogic({ experimentId: id }))

    useEffect(() => {
        loadExperiment()
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id])

    useEffect(() => {
        if (isExperimentLaunched && experiment && !isLegacyExperiment(experiment)) {
            loadExposures()
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isExperimentLaunched, experiment])

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    const isLegacy = experiment && isLegacyExperiment(experiment)
    const status = experiment ? getExperimentStatus(experiment) : null
    const hasResults = primaryMetricsResults?.length > 0 && primaryMetricsResults[0]

    // Find the most significant primary metric to display
    const bestMetric = findMostSignificantMetric(
        experiment?.metrics as ExperimentMetric[] | undefined,
        primaryMetricsResults
    )
    const totalPrimaryMetrics = experiment?.metrics?.length || 0

    return (
        <div>
            <BindLogic logic={experimentLogic} props={{ experimentId: id }}>
                {/* Header */}
                <div className="flex items-center gap-2 p-3">
                    <IconFlask className="text-lg shrink-0" />
                    {experimentLoading ? (
                        <LemonSkeleton className="h-6 flex-1" />
                    ) : (
                        <>
                            <span className="flex-1 font-semibold truncate">{experiment.name}</span>
                            {status && <StatusTag status={status} />}
                            {isExperimentLaunched && hasResults && !isLegacy && bestMetric && (
                                <ResultsTag isSignificant={bestMetric.isSignificant} />
                            )}
                        </>
                    )}
                </div>

                {/* Expanded Content */}
                {expanded && !experimentLoading && (
                    <>
                        <LemonDivider className="my-0" />

                        {/* Description */}
                        {experiment.description && (
                            <div className="px-3 pt-3 pb-1 text-sm">{experiment.description}</div>
                        )}

                        {/* Legacy experiment warning */}
                        {isLegacy && (
                            <div className="p-3">
                                <LemonBanner type="warning">
                                    <div>
                                        <strong>Legacy experiment</strong>
                                    </div>
                                    <div>
                                        This experiment uses legacy metrics. Results are only available in the full
                                        experiment view.
                                    </div>
                                </LemonBanner>
                            </div>
                        )}

                        {/* Draft state */}
                        {isExperimentDraft && !isLegacy && (
                            <div className="p-3">
                                <div className="text-sm text-muted mb-2">
                                    Experiment is in draft. Launch to start collecting data.
                                </div>
                                <div className="flex gap-4 text-sm text-muted">
                                    <span>{variants.length} variants</span>
                                    <span>{experiment.metrics?.length || 0} metrics</span>
                                </div>
                            </div>
                        )}

                        {/* Launched state with new metrics */}
                        {isExperimentLaunched && !isLegacy && (
                            <div className="p-3 space-y-3">
                                {/* Stats row */}
                                <div className="flex gap-6">
                                    <ExperimentStatItem
                                        label="Duration"
                                        value={formatDuration(experiment.start_date, experiment.end_date)}
                                    />
                                    <ExperimentStatItem
                                        label="Exposures"
                                        value={formatTotalExposures(exposures)}
                                        loading={exposuresLoading}
                                        chart={exposures ? <MicroChart exposures={exposures} /> : undefined}
                                    />
                                    <ExperimentStatItem label="Variants" value={variants.length} />
                                </div>

                                {/* Primary metric results - show most significant metric */}
                                {primaryMetricsResultsLoading ? (
                                    <div className="space-y-2">
                                        <LemonSkeleton className="h-4 w-48" />
                                        <LemonSkeleton className="h-24 w-full" />
                                    </div>
                                ) : bestMetric ? (
                                    <>
                                        {totalPrimaryMetrics > 1 && (
                                            <div className="text-xs text-muted mb-1">
                                                Showing most significant of {totalPrimaryMetrics} metrics
                                                {bestMetric.metric.name && `: ${bestMetric.metric.name}`}
                                            </div>
                                        )}
                                        <NotebookWinningVariantSummary
                                            result={bestMetric.result}
                                            metric={bestMetric.metric}
                                        />
                                        <NotebookCompactTable result={bestMetric.result} metric={bestMetric.metric} />
                                    </>
                                ) : (
                                    <div className="text-sm text-muted">Collecting data...</div>
                                )}
                            </div>
                        )}
                    </>
                )}
            </BindLogic>
        </div>
    )
}

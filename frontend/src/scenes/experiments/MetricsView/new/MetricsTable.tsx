import { useActions, useValues } from 'kea'

import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { ExperimentStatsMethod, InsightType } from '~/types'

import { experimentLogic } from '../../experimentLogic'
import { experimentMetricsLogic } from '../../experimentMetricsLogic'
import { isLaunched } from '../../experimentsLogic'
import { resolveSequentialEnabled } from '../../ExperimentView/sequential'
import { MetricRowGroup } from './MetricRowGroup'
import { TableHeader } from './TableHeader'

/**
 * True when any metric in this section is still being recalculated. Curried by the section's metrics so
 * each table judges only its own; exposures loading is the caller's concern.
 */
const sectionHasRecalculatingMetric =
    (metrics: ExperimentMetric[]) =>
    (recalculatingMetricUuids: string[]): boolean =>
        metrics.some(({ uuid }) => !!uuid && recalculatingMetricUuids.includes(uuid))

interface MetricsTableProps {
    metrics: ExperimentMetric[]
    results: (NewExperimentQueryResponse | undefined)[]
    errors: any[]
    metricIndexes: number[]
    isSecondary: boolean
    axisRange: number
    getInsightType: (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery) => InsightType
    showDetailsModal?: boolean
}

export function MetricsTable({
    metrics,
    results,
    errors,
    metricIndexes,
    isSecondary,
    axisRange,
    getInsightType,
    showDetailsModal = true,
}: MetricsTableProps): JSX.Element {
    const { experiment, exposuresLoading } = useValues(experimentLogic)
    const { recalculatingMetricUuids } = useValues(experimentMetricsLogic({ experiment }))
    const { experimentsConfig } = useValues(experimentsConfigLogic)
    const teamDefaultSequentialEnabled = experimentsConfig?.default_sequential_testing_enabled ?? false
    const sequentialTestingEnabled = resolveSequentialEnabled(
        experiment.stats_config?.frequentist,
        teamDefaultSequentialEnabled
    )
    const {
        duplicateMetric,
        updateExperimentMetrics,
        updateMetricBreakdown,
        removeMetricBreakdown,
        removeMetric,
        removeSharedMetricFromExperiment,
    } = useActions(experimentLogic)

    if (metrics.length === 0) {
        return (
            <div className="p-8 text-center border rounded-md">
                <div className="text-muted">No {isSecondary ? 'secondary' : 'primary'} metrics configured</div>
            </div>
        )
    }

    /**
     * Show this section's loader while any of its own metrics is loading: recalculating in place, or cold
     * (no result and no error yet). Exposures load globally, so they count for whichever section has metrics.
     */
    const hasColdMetric = metrics.some((_, index) => !results[index] && !errors[index])
    const sectionLoading =
        sectionHasRecalculatingMetric(metrics)(recalculatingMetricUuids) || hasColdMetric || exposuresLoading

    return (
        <div className="w-full overflow-x-auto rounded-md border">
            <table className="w-full border-collapse text-sm">
                <colgroup>
                    <col className="min-w-[200px]" />
                    <col />
                    <col />
                    <col />
                    <col />
                    <col />
                    <col className="min-w-[400px]" />
                </colgroup>
                <TableHeader
                    axisRange={axisRange}
                    statsMethod={experiment.stats_config?.method || ExperimentStatsMethod.Bayesian}
                    sequentialTestingEnabled={sequentialTestingEnabled}
                    loading={sectionLoading}
                />
                <tbody>
                    {metrics.map((metric, index) => {
                        const result = results[index]
                        const error = errors[index]
                        const metricIndex = metricIndexes[index]

                        const isLoading = !result && !error && isLaunched(experiment)

                        return (
                            <MetricRowGroup
                                key={metric.uuid || index}
                                metric={metric}
                                result={result ?? null}
                                experiment={experiment}
                                metricType={getInsightType(metric)}
                                metricIndex={metricIndex}
                                displayOrder={index}
                                axisRange={axisRange}
                                isSecondary={isSecondary}
                                isLastMetric={index === metrics.length - 1}
                                isAlternatingRow={index % 2 === 1}
                                onDuplicateMetric={() => {
                                    if (!metric.uuid || !experiment) {
                                        return
                                    }

                                    const newUuid = crypto.randomUUID()
                                    duplicateMetric({ uuid: metric.uuid, isSecondary, newUuid })
                                    updateExperimentMetrics()
                                }}
                                onDeleteMetric={() => {
                                    if (metric.isSharedMetric && metric.sharedMetricId) {
                                        removeSharedMetricFromExperiment(metric.sharedMetricId)
                                        return
                                    }
                                    if (!metric.uuid) {
                                        return
                                    }
                                    removeMetric(metric.uuid, isSecondary ? 'secondary' : 'primary')
                                }}
                                onBreakdownChange={(breakdown) => {
                                    if (!metric.uuid) {
                                        return
                                    }

                                    updateMetricBreakdown(metric.uuid, breakdown)
                                }}
                                onRemoveBreakdown={(index) => {
                                    if (!metric.uuid) {
                                        return
                                    }

                                    /**
                                     * we pass the breakdown just for instrumentation purposes
                                     */
                                    const breakdown = metric.breakdownFilter?.breakdowns?.[index]

                                    /**
                                     * throw an error if the breakdown is not found
                                     */
                                    if (!breakdown) {
                                        throw new Error('Breakdown not found')
                                    }

                                    removeMetricBreakdown(metric.uuid, index, breakdown)
                                }}
                                error={error}
                                isLoading={isLoading}
                                exposuresLoading={exposuresLoading}
                                showDetailsModal={showDetailsModal}
                            />
                        )
                    })}
                </tbody>
            </table>
        </div>
    )
}

import { DndContext, DragEndEvent, KeyboardSensor, PointerSensor, useSensor, useSensors } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { SortableContext, arrayMove, sortableKeyboardCoordinates, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'

import { verticalSortableListCollisionDetection } from 'lib/sortable'
import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import {
    ExperimentFunnelsQuery,
    ExperimentMetric,
    ExperimentTrendsQuery,
    NewExperimentQueryResponse,
} from '~/queries/schema/schema-general'
import { ExperimentStatsMethod, InsightType } from '~/types'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'

import { experimentLogic } from '../../experimentLogic'
import { experimentMetricsLogic } from '../../experimentMetricsLogic'
import { resolveSequentialEnabled } from '../../ExperimentView/sequential'
import { type ExperimentVariantResult, getDefaultMetricTitle, getVariantInterval } from '../shared/utils'
import { MAX_AXIS_RANGE } from './constants'
import { MetricRowGroup } from './MetricRowGroup'
import { SortableMetricRowGroup } from './SortableMetricRowGroup'
import { TableHeader } from './TableHeader'

const metricName = (metric: ExperimentMetric): string => metric.name || getDefaultMetricTitle(metric)

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
    results: NewExperimentQueryResponse[]
    errors: any[]
    metricIndexes: number[]
    isSecondary: boolean
    getInsightType: (metric: ExperimentMetric | ExperimentTrendsQuery | ExperimentFunnelsQuery) => InsightType
    showDetailsModal?: boolean
}

export function MetricsTable({
    metrics,
    results,
    errors,
    metricIndexes,
    isSecondary,
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
        duplicateSharedMetricAsInlineMetric,
        updateExperimentMetrics,
        updateMetricBreakdown,
        updateMetricBreakdownAttribution,
        updateMetricBreakdownLimit,
        removeMetricBreakdown,
        removeMetric,
        removeSharedMetricFromExperiment,
        reorderMetrics,
    } = useActions(experimentLogic)

    const sensors = useSensors(
        useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
        useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates })
    )

    const orderedUuids = metrics.map(({ uuid }) => uuid).filter(Boolean) as string[]
    // Ordering is keyed by uuid, so a metric without one can't take part.
    const dragDisabled = orderedUuids.length !== metrics.length || metrics.length < 2

    const handleDragEnd = ({ active, over }: DragEndEvent): void => {
        if (!over || active.id === over.id) {
            return
        }

        const from = orderedUuids.indexOf(active.id as string)
        const to = orderedUuids.indexOf(over.id as string)

        if (from === -1 || to === -1) {
            return
        }

        reorderMetrics(isSecondary, arrayMove(orderedUuids, from, to))
    }

    const nameByUuid = new Map(metrics.map((metric) => [metric.uuid, metricName(metric)]))
    const announcements = {
        onDragStart: ({ active }: { active: { id: string | number } }) =>
            `Picked up ${nameByUuid.get(String(active.id))}.`,
        onDragOver: ({ active, over }: { active: { id: string | number }; over: { id: string | number } | null }) =>
            over
                ? `${nameByUuid.get(String(active.id))} moved to position ${
                      orderedUuids.indexOf(String(over.id)) + 1
                  } of ${orderedUuids.length}.`
                : undefined,
        onDragEnd: ({ active, over }: { active: { id: string | number }; over: { id: string | number } | null }) =>
            over
                ? `${nameByUuid.get(String(active.id))} dropped at position ${
                      orderedUuids.indexOf(String(over.id)) + 1
                  } of ${orderedUuids.length}.`
                : `${nameByUuid.get(String(active.id))} returned to its original position.`,
        onDragCancel: ({ active }: { active: { id: string | number } }) =>
            `Reordering cancelled. ${nameByUuid.get(String(active.id))} returned to its original position.`,
    }

    // Calculate shared axisRange across all metrics
    let hasBreakdowns = false
    const allIntervalValues = results.flatMap((result: NewExperimentQueryResponse) => {
        const allVariants: ExperimentVariantResult[] = []

        // Include main variant results
        if (result?.variant_results) {
            allVariants.push(...result.variant_results)
        }

        // Include breakdown variant results
        if (result?.breakdown_results && result.breakdown_results.length > 0) {
            hasBreakdowns = true
            result.breakdown_results.forEach((breakdownResult) => {
                if (breakdownResult?.variants) {
                    allVariants.push(...breakdownResult.variants)
                }
            })
        }

        return allVariants.flatMap((variant: ExperimentVariantResult) => {
            const interval = getVariantInterval(variant)
            return interval ? [Math.abs(interval[0]), Math.abs(interval[1])] : []
        })
    })

    // Use 0 as default if no intervals exist, otherwise get the maximum value
    const maxAbsValue = allIntervalValues.length > 0 ? Math.max(...allIntervalValues) : 0
    const axisMargin = Math.max(maxAbsValue * 0.05, 0.1)
    // When breakdowns are present, ignore MAX_AXIS_RANGE to show full range of breakdown data
    const axisRange = hasBreakdowns ? maxAbsValue + axisMargin : Math.min(maxAbsValue + axisMargin, MAX_AXIS_RANGE)

    if (metrics.length === 0) {
        return (
            <div className="p-8 text-center border rounded-md">
                <div className="text-muted">No {isSecondary ? 'secondary' : 'primary'} metrics configured</div>
            </div>
        )
    }

    const hasColdMetric = isLaunched(experiment) && metrics.some((_, index) => !results[index] && !errors[index])
    const sectionLoading =
        sectionHasRecalculatingMetric(metrics)(recalculatingMetricUuids) || hasColdMetric || exposuresLoading

    return (
        <DndContext
            sensors={sensors}
            // Metric groups vary from one row to many, which is exactly where closestCenter misjudges.
            collisionDetection={verticalSortableListCollisionDetection}
            modifiers={[restrictToVerticalAxis, restrictToParentElement]}
            // The wrapper is overflow-x-auto, which makes it a scroll container on both axes. Left to
            // auto-scroll it chases the dragged group past its own bounds, growing scrollHeight until
            // the rows scroll out of view. The page still scrolls normally.
            autoScroll={{ canScroll: (element) => element === document.scrollingElement }}
            accessibility={{ announcements }}
            onDragEnd={handleDragEnd}
        >
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
                    <SortableContext items={orderedUuids} strategy={verticalListSortingStrategy}>
                        {metrics.map((metric, index) => {
                            const result = results[index]
                            const error = errors[index]
                            const metricIndex = metricIndexes[index]

                            const isLoading = !result && !error && isLaunched(experiment)

                            return (
                                <SortableMetricRowGroup
                                    key={metric.uuid || index}
                                    uuid={metric.uuid || String(index)}
                                    metricName={metricName(metric)}
                                    disabled={dragDisabled}
                                    isLastMetric={index === metrics.length - 1}
                                >
                                    {(dragHandle) => (
                                        <MetricRowGroup
                                            metric={metric}
                                            dragHandle={dragHandle}
                                            result={result}
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
                                            onDuplicateAsSingleUseMetric={() => {
                                                if (!metric.isSharedMetric || !metric.sharedMetricId || !experiment) {
                                                    return
                                                }

                                                const newUuid = crypto.randomUUID()
                                                duplicateSharedMetricAsInlineMetric({
                                                    sharedMetricId: metric.sharedMetricId,
                                                    isSecondary,
                                                    newUuid,
                                                })
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
                                            onBreakdownAttributionChange={(attributionType, attributionValue) => {
                                                if (!metric.uuid) {
                                                    return
                                                }

                                                updateMetricBreakdownAttribution(
                                                    metric.uuid,
                                                    attributionType,
                                                    attributionValue
                                                )
                                            }}
                                            onBreakdownLimitChange={(breakdownLimit) => {
                                                if (!metric.uuid) {
                                                    return
                                                }

                                                updateMetricBreakdownLimit(metric.uuid, breakdownLimit)
                                            }}
                                            error={error}
                                            isLoading={isLoading}
                                            exposuresLoading={exposuresLoading}
                                            showDetailsModal={showDetailsModal}
                                        />
                                    )}
                                </SortableMetricRowGroup>
                            )
                        })}
                    </SortableContext>
                </table>
            </div>
        </DndContext>
    )
}

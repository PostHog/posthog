import { DragEndEvent, KeyboardSensor, PointerSensor, SensorDescriptor, useSensor, useSensors } from '@dnd-kit/core'
import { arrayMove, sortableKeyboardCoordinates } from '@dnd-kit/sortable'
import { useActions, useValues } from 'kea'

import { experimentsConfigLogic } from 'scenes/settings/environment/experimentsConfigLogic'

import { Breakdown, ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'
import { BreakdownAttributionType, Experiment, ExperimentStatsMethod } from '~/types'

import { isLaunched } from 'products/experiments/frontend/experimentStatus'

import { experimentLogic } from '../../experimentLogic'
import { experimentMetricsLogic } from '../../experimentMetricsLogic'
import { resolveSequentialEnabled } from '../../ExperimentView/sequential'
import { type ExperimentVariantResult, getDefaultMetricTitle, getVariantInterval } from '../shared/utils'
import { MAX_AXIS_RANGE } from './constants'

export const metricName = (metric: ExperimentMetric): string => metric.name || getDefaultMetricTitle(metric)

export interface MetricHandlers {
    onDuplicateMetric: () => void
    onDuplicateAsSingleUseMetric: () => void
    onDeleteMetric: () => void
    onBreakdownChange: (breakdown: Breakdown) => void
    onRemoveBreakdown: (index: number) => void
    onBreakdownAttributionChange: (attributionType: BreakdownAttributionType, attributionValue?: number) => void
    onBreakdownLimitChange: (breakdownLimit: number) => void
}

type DragAnnouncements = {
    onDragStart: (event: { active: { id: string | number } }) => string
    onDragOver: (event: { active: { id: string | number }; over: { id: string | number } | null }) => string | undefined
    onDragEnd: (event: { active: { id: string | number }; over: { id: string | number } | null }) => string
    onDragCancel: (event: { active: { id: string | number } }) => string
}

export interface MetricsTableModel {
    experiment: Experiment
    exposuresLoading: boolean
    axisRange: number
    sectionLoading: boolean
    statsMethod: ExperimentStatsMethod
    sequentialTestingEnabled: boolean
    sensors: SensorDescriptor<any>[]
    orderedUuids: string[]
    dragDisabled: boolean
    handleDragEnd: (event: DragEndEvent) => void
    announcements: DragAnnouncements
    handlersFor: (metric: ExperimentMetric) => MetricHandlers
}

/**
 * True when any metric in this section is still being recalculated. Curried by the section's metrics so
 * each table judges only its own; exposures loading is the caller's concern.
 */
const sectionHasRecalculatingMetric =
    (metrics: ExperimentMetric[]) =>
    (recalculatingMetricUuids: string[]): boolean =>
        metrics.some(({ uuid }) => !!uuid && recalculatingMetricUuids.includes(uuid))

/** What the Lemon metrics table and the quill metric cards share: the axis, the reordering and the metric actions. */
export function useMetricsTableModel({
    metrics,
    results,
    errors,
    isSecondary,
}: {
    metrics: ExperimentMetric[]
    results: (NewExperimentQueryResponse | undefined)[]
    errors: any[]
    isSecondary: boolean
}): MetricsTableModel {
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
    const announcements: DragAnnouncements = {
        onDragStart: ({ active }) => `Picked up ${nameByUuid.get(String(active.id))}.`,
        onDragOver: ({ active, over }) =>
            over
                ? `${nameByUuid.get(String(active.id))} moved to position ${
                      orderedUuids.indexOf(String(over.id)) + 1
                  } of ${orderedUuids.length}.`
                : undefined,
        onDragEnd: ({ active, over }) =>
            over
                ? `${nameByUuid.get(String(active.id))} dropped at position ${
                      orderedUuids.indexOf(String(over.id)) + 1
                  } of ${orderedUuids.length}.`
                : `${nameByUuid.get(String(active.id))} returned to its original position.`,
        onDragCancel: ({ active }) =>
            `Reordering cancelled. ${nameByUuid.get(String(active.id))} returned to its original position.`,
    }

    // Calculate shared axisRange across all metrics
    let hasBreakdowns = false
    const allIntervalValues = results.flatMap((result: NewExperimentQueryResponse | undefined) => {
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

    const hasColdMetric = isLaunched(experiment) && metrics.some((_, index) => !results[index] && !errors[index])
    const sectionLoading = sectionHasRecalculatingMetric(metrics)(recalculatingMetricUuids) || hasColdMetric

    const handlersFor = (metric: ExperimentMetric): MetricHandlers => ({
        onDuplicateMetric: () => {
            if (!metric.uuid || !experiment) {
                return
            }

            const newUuid = crypto.randomUUID()
            duplicateMetric({ uuid: metric.uuid, isSecondary, newUuid })
            updateExperimentMetrics()
        },
        onDuplicateAsSingleUseMetric: () => {
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
        },
        onDeleteMetric: () => {
            if (metric.isSharedMetric && metric.sharedMetricId) {
                removeSharedMetricFromExperiment(metric.sharedMetricId)
                return
            }
            if (!metric.uuid) {
                return
            }
            removeMetric(metric.uuid, isSecondary ? 'secondary' : 'primary')
        },
        onBreakdownChange: (breakdown) => {
            if (!metric.uuid) {
                return
            }

            updateMetricBreakdown(metric.uuid, breakdown)
        },
        onRemoveBreakdown: (index) => {
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
        },
        onBreakdownAttributionChange: (attributionType, attributionValue) => {
            if (!metric.uuid) {
                return
            }

            updateMetricBreakdownAttribution(metric.uuid, attributionType, attributionValue)
        },
        onBreakdownLimitChange: (breakdownLimit) => {
            if (!metric.uuid) {
                return
            }

            updateMetricBreakdownLimit(metric.uuid, breakdownLimit)
        },
    })

    return {
        experiment,
        exposuresLoading,
        axisRange,
        sectionLoading,
        statsMethod: experiment.stats_config?.method || ExperimentStatsMethod.Bayesian,
        sequentialTestingEnabled,
        sensors,
        orderedUuids,
        dragDisabled,
        handleDragEnd,
        announcements,
        handlersFor,
    }
}

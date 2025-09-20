import { getSeriesColor as getSeriesColorFromLib } from 'lib/colors'
import { FunnelLayout } from 'lib/constants'
import { flattenedStepsByBreakdown, stepsWithConversionMetrics } from 'scenes/funnels/funnelUtils'

import {
    FlattenedFunnelStepByBreakdown,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
} from '~/types'

export interface FunnelDataProcessingOptions {
    stepReference?: FunnelStepReference
    disableBaseline?: boolean
    hiddenLegendBreakdowns?: string[]
}

export interface ProcessedFunnelData {
    steps: FunnelStepWithNestedBreakdown[]
    stepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    visibleStepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    flattenedBreakdowns: FlattenedFunnelStepByBreakdown[]
    hasFunnelResults: boolean
}

/**
 * Get a consistent color for a funnel series using the same index-based approach as exposure charts.
 */
export function getSeriesColor(series: FunnelStepWithConversionMetrics): string {
    // Use the breakdownIndex if available (added by experiment conversion)
    // This matches exactly what the exposure chart does with getSeriesColor(index)
    const index = (series as any).breakdownIndex ?? 0
    return getSeriesColorFromLib(index)
}

/**
 * Processes raw funnel step data into the format needed for visualization components.
 * This extracts the core data processing logic from funnelDataLogic.
 */
export function processFunnelData(
    steps: FunnelStepWithNestedBreakdown[],
    options: FunnelDataProcessingOptions = {}
): ProcessedFunnelData {
    const { stepReference = FunnelStepReference.total, disableBaseline = false, hiddenLegendBreakdowns = [] } = options

    // Sort steps by order (same as funnelDataLogic)
    const sortedSteps = steps.sort((a, b) => a.order - b.order)

    // Calculate conversion metrics
    const stepsWithMetrics = stepsWithConversionMetrics(sortedSteps, stepReference)

    // Flatten breakdowns for legend display (always use vertical layout)
    const flattenedBreakdowns = flattenedStepsByBreakdown(
        stepsWithMetrics,
        FunnelLayout.vertical,
        disableBaseline,
        true
    )

    // Filter visible steps based on hidden legend breakdowns
    const visibleSteps = getVisibleStepsWithConversionMetrics(
        stepsWithMetrics,
        flattenedBreakdowns,
        hiddenLegendBreakdowns
    )

    // Check if we have valid funnel results
    const hasFunnelResults = !!(sortedSteps && sortedSteps[0] && sortedSteps[0].count > -1)

    return {
        steps: sortedSteps,
        stepsWithConversionMetrics: stepsWithMetrics,
        visibleStepsWithConversionMetrics: visibleSteps,
        flattenedBreakdowns,
        hasFunnelResults,
    }
}

/**
 * Filters steps based on hidden legend breakdowns (extracted from funnelDataLogic).
 */
function getVisibleStepsWithConversionMetrics(
    steps: FunnelStepWithConversionMetrics[],
    flattenedBreakdowns: FlattenedFunnelStepByBreakdown[],
    hiddenLegendBreakdowns: string[]
): FunnelStepWithConversionMetrics[] {
    const isOnlySeries = flattenedBreakdowns.length <= 1
    const baseLineSteps = flattenedBreakdowns.find((b) => b.isBaseline)

    return steps.map((step, stepIndex) => ({
        ...step,
        nested_breakdown: (baseLineSteps?.steps
            ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
            : step?.nested_breakdown
        )
            ?.map((b, breakdownIndex) => ({
                ...b,
                order: breakdownIndex,
            }))
            ?.filter((b) => isOnlySeries || !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))),
    }))
}

/**
 * Helper function to get visibility key for breakdown values.
 */
function getVisibilityKey(breakdownValue: any): string {
    if (Array.isArray(breakdownValue)) {
        return breakdownValue.join('::')
    }
    return String(breakdownValue ?? '')
}

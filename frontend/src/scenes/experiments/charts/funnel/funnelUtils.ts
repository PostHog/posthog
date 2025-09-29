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
    const { stepReference = FunnelStepReference.total } = options

    // Sort steps by order (same as funnelDataLogic)
    const sortedSteps = steps.sort((a, b) => a.order - b.order)

    // Calculate conversion metrics
    const stepsWithMetrics = stepsWithConversionMetrics(sortedSteps, stepReference)

    // Flatten breakdowns for legend display (always use vertical layout)
    const flattenedBreakdowns = flattenedStepsByBreakdown(stepsWithMetrics, FunnelLayout.vertical, true)

    // Check if we have valid funnel results
    const hasFunnelResults = !!(sortedSteps && sortedSteps[0] && sortedSteps[0].count > -1)

    return {
        steps: sortedSteps,
        stepsWithConversionMetrics: stepsWithMetrics,
        flattenedBreakdowns,
        hasFunnelResults,
    }
}

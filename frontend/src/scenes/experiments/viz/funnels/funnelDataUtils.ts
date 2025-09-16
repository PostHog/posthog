import { FunnelLayout } from 'lib/constants'
import {
    FlattenedFunnelStepByBreakdown,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelVizType,
    FunnelsTimeConversionBins,
    HistogramGraphDatum,
} from '~/types'
import { percentage, sum } from 'lib/utils'
import { flattenedStepsByBreakdown, stepsWithConversionMetrics } from './funnelUtils'

export interface FunnelDataProcessingOptions {
    stepReference?: FunnelStepReference
    layout?: FunnelLayout
    disableBaseline?: boolean
    hiddenLegendBreakdowns?: string[]
}

export interface ProcessedFunnelData {
    steps: FunnelStepWithNestedBreakdown[]
    stepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    visibleStepsWithConversionMetrics: FunnelStepWithConversionMetrics[]
    flattenedBreakdowns: FlattenedFunnelStepByBreakdown[]
    histogramGraphData?: HistogramGraphDatum[]
    hasFunnelResults: boolean
}

/**
 * Processes raw funnel step data into the format needed for visualization components.
 * This extracts the core data processing logic from funnelDataLogic.
 */
export function processFunnelData(
    steps: FunnelStepWithNestedBreakdown[],
    options: FunnelDataProcessingOptions = {}
): ProcessedFunnelData {
    const {
        stepReference = FunnelStepReference.total,
        layout = FunnelLayout.vertical,
        disableBaseline = false,
        hiddenLegendBreakdowns = [],
    } = options

    // Sort steps by order (same as funnelDataLogic)
    const sortedSteps = steps.sort((a, b) => a.order - b.order)

    // Calculate conversion metrics
    const stepsWithMetrics = stepsWithConversionMetrics(sortedSteps, stepReference)

    // Flatten breakdowns for legend display
    const flattenedBreakdowns = flattenedStepsByBreakdown(stepsWithMetrics, layout, disableBaseline, true)

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
 * Processes time-to-convert data for histogram visualization.
 */
export function processTimeConversionData(
    timeConversionResults: FunnelsTimeConversionBins
): HistogramGraphDatum[] | null {
    if ((timeConversionResults?.bins?.length ?? 0) < 2) {
        return null // There are no results
    }

    const totalCount = sum(timeConversionResults.bins.map(([, count]) => count))
    if (totalCount === 0) {
        return [] // Nobody has converted in the time period
    }

    const binSize = timeConversionResults.bins[1][0] - timeConversionResults.bins[0][0]
    return timeConversionResults.bins.map(([id, count]: [id: number, count: number]) => {
        const value = Math.max(0, id)
        const percent = totalCount === 0 ? 0 : count / totalCount
        return {
            id: value,
            bin0: value,
            bin1: value + binSize,
            count,
            label: percent === 0 ? '' : percentage(percent, 1, true),
        }
    })
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
            ?.filter(
                (b) =>
                    isOnlySeries ||
                    !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
            ),
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
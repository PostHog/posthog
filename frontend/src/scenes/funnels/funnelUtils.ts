import { clamp, compactNumber } from 'lib/utils'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { getChartColors } from 'lib/colors'
import api from 'lib/api'
import {
    FilterType,
    FunnelStepRangeEntityFilter,
    FunnelRequestParams,
    FunnelResult,
    FunnelStep,
    FunnelStepWithNestedBreakdown,
    FunnelsTimeConversionBins,
} from '~/types'

const PERCENTAGE_DISPLAY_PRECISION = 1 // Number of decimals to show in percentages

export function formatDisplayPercentage(percentage: number): string {
    if (Number.isNaN(percentage)) {
        percentage = 0
    }
    // Returns a formatted string properly rounded to ensure consistent results
    return (percentage * 100).toFixed(PERCENTAGE_DISPLAY_PRECISION)
}

export function getReferenceStep<T>(steps: T[], stepReference: FunnelStepReference, index?: number): T {
    // Step to serve as denominator of percentage calculations.
    // step[0] is full-funnel conversion, previous is relative.
    if (!index || index <= 0) {
        return steps[0]
    }
    switch (stepReference) {
        case FunnelStepReference.previous:
            return steps[index - 1]
        case FunnelStepReference.total:
        default:
            return steps[0]
    }
}

// Gets last filled step if steps[index] is empty.
// Useful in calculating total and average times for total conversions where the last step has 0 count
export function getLastFilledStep(steps: FunnelStep[], index?: number): FunnelStep {
    const firstIndex = Math.min(steps.length, Math.max(0, index || steps.length - 1)) + 1
    return (
        steps
            .slice(0, firstIndex)
            .reverse()
            .find((s) => s.count > 0) || steps[0]
    )
}

export function humanizeOrder(order: number): number {
    return order + 1
}

export function getSeriesColor(index?: number): string | undefined {
    if (typeof index === 'number' && index >= 0) {
        return getChartColors('white')[index]
    }
}

export function getBreakdownMaxIndex(breakdown?: FunnelStep[]): number | undefined {
    // Returns the index of the last nonzero breakdown item
    if (!breakdown) {
        return
    }
    const nonZeroCounts = breakdown.map(({ count }, index) => ({ count, index })).filter(({ count }) => !!count)
    if (!nonZeroCounts.length) {
        return
    }
    return nonZeroCounts[nonZeroCounts.length - 1].index
}

export function getSeriesPositionName(
    index?: number,
    breakdownMaxIndex?: number
): 'first' | 'last' | 'only' | undefined {
    if (!breakdownMaxIndex) {
        return 'only'
    }
    if (typeof index === 'number') {
        return index === 0 ? 'first' : index === breakdownMaxIndex ? 'last' : undefined
    }
    return
}

export function humanizeStepCount(count?: number): string {
    if (typeof count === 'undefined') {
        return ''
    }
    return count > 9999 ? compactNumber(count) : count.toLocaleString()
}

export function cleanBinResult(binsResult: FunnelsTimeConversionBins): FunnelsTimeConversionBins {
    return {
        ...binsResult,
        bins: binsResult.bins.map(([time, count]) => [time ?? 0, count ?? 0]),
        average_conversion_time: binsResult.average_conversion_time ?? 0,
    }
}

export function aggregateBreakdownResult(
    breakdownList: FunnelStep[][],
    breakdownProperty?: string | number | number[]
): FunnelStepWithNestedBreakdown[] {
    if (breakdownList.length) {
        return breakdownList[0].map((step, i) => ({
            ...step,
            count: breakdownList.reduce((total, breakdownSteps) => total + breakdownSteps[i].count, 0),
            breakdown: breakdownProperty,
            nested_breakdown: breakdownList.reduce(
                (allEntries, breakdownSteps) => [...allEntries, breakdownSteps[i]],
                []
            ),
            average_conversion_time: null,
            people: [],
        }))
    }
    return []
}

export function isBreakdownFunnelResults(results: FunnelStep[] | FunnelStep[][]): results is FunnelStep[][] {
    return Array.isArray(results) && (results.length === 0 || Array.isArray(results[0]))
}

// breakdown parameter could be a string (property breakdown) or object/number (list of cohort ids)
export function isValidBreakdownParameter(breakdown: FunnelRequestParams['breakdown']): boolean {
    return ['string', 'null', 'undefined', 'number'].includes(typeof breakdown) || Array.isArray(breakdown)
}

export function wait(ms = 1000): Promise<any> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

export const SECONDS_TO_POLL = 3 * 60

export const EMPTY_FUNNEL_RESULTS = {
    results: [],
    timeConversionResults: {
        bins: [],
        average_conversion_time: 0,
    },
}

export async function pollFunnel<T = FunnelStep[]>(apiParams: FunnelRequestParams): Promise<FunnelResult<T>> {
    // Tricky: This API endpoint has wildly different return types depending on parameters.
    const { refresh, ...bodyParams } = apiParams
    let result = await api.create('api/insight/funnel/?' + (refresh ? 'refresh=true' : ''), bodyParams)
    const start = window.performance.now()
    while (result.result.loading && (window.performance.now() - start) / 1000 < SECONDS_TO_POLL) {
        await wait()
        result = await api.create('api/insight/funnel', bodyParams)
    }
    // if endpoint is still loading after 3 minutes just return default
    if (result.loading) {
        throw { status: 0, statusText: 'Funnel timeout' }
    }
    return result
}

export const isStepsEmpty = (filters: FilterType): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0

export const deepCleanFunnelExclusionEvents = (filters: FilterType): FunnelStepRangeEntityFilter[] | undefined => {
    if (!filters.exclusions) {
        return filters.exclusions
    }

    const lastIndex = Math.max((filters.events?.length || 0) + (filters.actions?.length || 0) - 1, 1)
    return filters.exclusions.map((event) => {
        const funnel_from_step = event.funnel_from_step ? clamp(event.funnel_from_step, 0, lastIndex - 1) : 0
        return {
            ...event,
            ...{ funnel_from_step },
            ...{
                funnel_to_step: event.funnel_to_step
                    ? clamp(event.funnel_to_step, funnel_from_step + 1, lastIndex)
                    : lastIndex,
            },
        }
    })
}

export const getClampedStepRangeFilter = ({
    stepRange,
    filters,
}: {
    stepRange?: FunnelStepRangeEntityFilter
    filters: FilterType
}): FunnelStepRangeEntityFilter => {
    const maxStepIndex = Math.max((filters.events?.length || 0) + (filters.actions?.length || 0) - 1, 1)
    const funnel_from_step = clamp(stepRange?.funnel_from_step ?? filters.funnel_from_step ?? 0, 0, maxStepIndex)
    return {
        ...(stepRange as FunnelStepRangeEntityFilter),
        funnel_from_step,
        funnel_to_step: clamp(
            stepRange?.funnel_to_step ?? filters.funnel_to_step ?? maxStepIndex,
            funnel_from_step + 1,
            maxStepIndex
        ),
    }
}

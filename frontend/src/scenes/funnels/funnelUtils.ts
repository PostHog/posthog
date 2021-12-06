import { clamp, compactNumber, humanFriendlyDuration } from 'lib/utils'
import { getChartColors } from 'lib/colors'
import api from 'lib/api'
import {
    FilterType,
    FunnelStepRangeEntityFilter,
    FunnelRequestParams,
    FunnelResult,
    FunnelStep,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    BreakdownKeyType,
    FunnelsTimeConversionBins,
    FunnelAPIResponse,
    FunnelStepReference,
    TeamType,
    FlattenedFunnelStepByBreakdown,
} from '~/types'

const PERCENTAGE_DISPLAY_PRECISION = 1 // Number of decimals to show in percentages

const EMPTY_BREAKDOWN_KEY = '__empty_string__'
const EMPTY_BREAKDOWN_VALUE = '(empty string)'
export const EMPTY_BREAKDOWN_VALUES = {
    rowKey: EMPTY_BREAKDOWN_KEY,
    breakdown: [EMPTY_BREAKDOWN_KEY], // unique key not to be used by backend in calculating breakdowns
    breakdown_value: [EMPTY_BREAKDOWN_VALUE],
    isEmpty: true,
}

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

export function getSeriesColor(index?: number, isSingleSeries: boolean = false, fallbackColor?: string): string {
    if (isSingleSeries) {
        return 'var(--primary)'
    }
    if (typeof index === 'number' && index >= 0) {
        return getChartColors('white')[index]
    }
    return fallbackColor ?? getChartColors('white')[0]
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

export function createPopoverMetrics(
    breakdown: Omit<FunnelStepWithConversionMetrics, 'nested_breakdown'>,
    currentOrder = 0,
    previousOrder = 0
): { title: string; value: number | string; visible?: boolean }[] {
    return [
        {
            title: 'Completed step',
            value: breakdown.count,
        },
        {
            title: 'Conversion rate (total)',
            value: formatDisplayPercentage(breakdown.conversionRates.total) + '%',
        },
        {
            title: `Conversion rate (from step ${humanizeOrder(previousOrder)})`,
            value: formatDisplayPercentage(breakdown.conversionRates.fromPrevious) + '%',
            visible: currentOrder !== 0,
        },
        {
            title: 'Dropped off',
            value: breakdown.droppedOffFromPrevious,
            visible: currentOrder !== 0 && breakdown.droppedOffFromPrevious > 0,
        },
        {
            title: `Dropoff rate (from step ${humanizeOrder(previousOrder)})`,
            value: formatDisplayPercentage(1 - breakdown.conversionRates.fromPrevious) + '%',
            visible: currentOrder !== 0 && breakdown.droppedOffFromPrevious > 0,
        },
        {
            title: 'Average time on step',
            value: humanFriendlyDuration(breakdown.average_conversion_time),
            visible: !!breakdown.average_conversion_time,
        },
    ]
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

export function cleanBinResult(result: FunnelResult): FunnelResult {
    const binsResult = result.result as FunnelsTimeConversionBins
    return {
        ...result,
        result: {
            ...result.result,
            bins: binsResult.bins?.map(([time, count]) => [time ?? 0, count ?? 0]) ?? [],
            average_conversion_time: binsResult.average_conversion_time ?? 0,
        },
    }
}

export function aggregateBreakdownResult(
    breakdownList: FunnelStep[][],
    breakdownProperty?: BreakdownKeyType
): FunnelStepWithNestedBreakdown[] {
    if (breakdownList.length) {
        // Create mapping to determine breakdown ordering by first step counts
        const breakdownToOrderMap: Record<string | number, FunnelStep> = breakdownList
            .reduce<{ breakdown_value: (string | number)[]; count: number }[]>(
                (allEntries, breakdownSteps) => [
                    ...allEntries,
                    {
                        breakdown_value: getBreakdownStepValues(breakdownSteps?.[0], -1).breakdown_value,
                        count: breakdownSteps?.[0]?.count ?? 0,
                    },
                ],
                []
            )
            .sort((a, b) => b.count - a.count)
            .reduce(
                (allEntries, breakdown, order) => ({
                    ...allEntries,
                    [breakdown.breakdown_value.join('_')]: { ...breakdown, order },
                }),
                {}
            )

        return breakdownList[0].map((step, i) => ({
            ...step,
            count: breakdownList.reduce((total, breakdownSteps) => total + breakdownSteps[i].count, 0),
            breakdown: breakdownProperty,
            nested_breakdown: breakdownList
                .reduce(
                    (allEntries, breakdownSteps) => [
                        ...allEntries,
                        {
                            ...breakdownSteps[i],
                            order: breakdownToOrderMap[
                                getBreakdownStepValues(breakdownSteps[i], i).breakdown_value.join('_')
                            ].order,
                        },
                    ],
                    []
                )
                .sort((a, b) => a.order - b.order),
            average_conversion_time: null,
            people: [],
        }))
    }
    return []
}

export function isBreakdownFunnelResults(results: FunnelAPIResponse): results is FunnelStep[][] {
    return Array.isArray(results) && (results.length === 0 || Array.isArray(results[0]))
}

// breakdown parameter could be a string (property breakdown) or object/number (list of cohort ids)
export function isValidBreakdownParameter(
    breakdown: FunnelRequestParams['breakdown'],
    breakdowns: FunnelRequestParams['breakdowns']
): boolean {
    return (
        (Array.isArray(breakdowns) && breakdowns.length > 0) ||
        ['string', 'null', 'undefined', 'number'].includes(typeof breakdown) ||
        Array.isArray(breakdown)
    )
}

export function wait(ms = 1000): Promise<any> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

export function getVisibilityIndex(step: FunnelStep, key?: BreakdownKeyType): string {
    if (step.type === 'actions') {
        return `${step.type}/${step.action_id}/${step.order}`
    } else {
        const breakdownValues = getBreakdownStepValues({ breakdown: key, breakdown_value: key }, -1).breakdown_value
        return `${step.type}/${step.action_id}/${step.order}/${breakdownValues.join('_')}`
    }
}

export const SECONDS_TO_POLL = 3 * 60

export async function pollFunnel<T = FunnelStep[] | FunnelsTimeConversionBins>(
    teamId: TeamType['id'],
    apiParams: FunnelRequestParams
): Promise<FunnelResult<T>> {
    // Tricky: This API endpoint has wildly different return types depending on parameters.
    const { refresh, ...bodyParams } = apiParams
    let result = await api.create(
        `api/projects/${teamId}/insights/funnel/${refresh ? '?refresh=true' : ''}`,
        bodyParams
    )
    const start = window.performance.now()
    while (result.result?.loading && (window.performance.now() - start) / 1000 < SECONDS_TO_POLL) {
        await wait()
        result = await api.create(`api/projects/${teamId}/insights/funnel`, bodyParams)
    }
    // if endpoint is still loading after 3 minutes just return default
    if (result.loading) {
        throw { status: 0, statusText: 'Funnel timeout' }
    }
    return result
}

interface BreakdownStepValues {
    rowKey: string
    breakdown: (string | number)[]
    breakdown_value: (string | number)[]
    isEmpty?: boolean
}

export const getBreakdownStepValues = (
    breakdownStep: Pick<FlattenedFunnelStepByBreakdown, 'breakdown' | 'breakdown_value'>,
    index: number,
    isBaseline: boolean = false
): BreakdownStepValues => {
    // Standardize all breakdown values to arrays of strings
    if (!breakdownStep) {
        return EMPTY_BREAKDOWN_VALUES
    }
    if (
        isBaseline ||
        breakdownStep?.breakdown_value === 'Baseline' ||
        breakdownStep?.breakdown_value?.[0] === 'Baseline'
    ) {
        return {
            rowKey: 'baseline_0',
            breakdown: ['baseline'],
            breakdown_value: ['Baseline'],
        }
    }
    if (Array.isArray(breakdownStep.breakdown) && !!breakdownStep.breakdown?.[0]) {
        // At this point, breakdown values are of type (string | number)[] with at least one valid breakdown type
        return {
            rowKey: `${breakdownStep.breakdown.join('_')}_${index}`,
            breakdown: breakdownStep.breakdown,
            breakdown_value: breakdownStep.breakdown_value as (string | number)[],
        }
    }
    if (!Array.isArray(breakdownStep.breakdown) && !!breakdownStep.breakdown) {
        // At this point, breakdown values are string | number
        return {
            rowKey: `${breakdownStep.breakdown}_${index}`,
            breakdown: [breakdownStep.breakdown],
            breakdown_value: [breakdownStep.breakdown_value as string | number],
        }
    }
    // Differentiate 'other' values that have nullish breakdown values.
    return EMPTY_BREAKDOWN_VALUES
}

export const isStepsEmpty = (filters: FilterType): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0

export const isStepsUndefined = (filters: FilterType): boolean =>
    typeof filters.events === 'undefined' && (typeof filters.actions === 'undefined' || filters.actions.length === 0)

export const deepCleanFunnelExclusionEvents = (filters: FilterType): FunnelStepRangeEntityFilter[] | undefined => {
    if (!filters.exclusions) {
        return undefined
    }

    const lastIndex = Math.max((filters.events?.length || 0) + (filters.actions?.length || 0) - 1, 1)
    const exclusions = filters.exclusions.map((event) => {
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
    return exclusions.length > 0 ? exclusions : undefined
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

export function getMeanAndStandardDeviation(values?: number[]): number[] {
    if (!values?.length) {
        return [0, 100]
    }

    const n = values.length
    const average = values.reduce((acc, current) => current + acc, 0) / n
    const squareDiffs = values.map((value) => {
        const diff = value - average
        return diff * diff
    })
    const avgSquareDiff = squareDiffs.reduce((acc, current) => current + acc, 0) / n
    return [average, Math.sqrt(avgSquareDiff)]
}

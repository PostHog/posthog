import { autoCaptureEventToDescription, clamp } from 'lib/utils'
import {
    FunnelExclusion,
    FunnelStep,
    FunnelStepWithNestedBreakdown,
    BreakdownKeyType,
    FunnelResultType,
    FunnelStepReference,
    FunnelConversionWindow,
    FunnelsFilterType,
    Breakdown,
    FunnelStepWithConversionMetrics,
    FlattenedFunnelStepByBreakdown,
    FunnelCorrelation,
    AnyPropertyFilter,
    PropertyOperator,
    ElementPropertyFilter,
    PropertyFilterType,
    FunnelCorrelationResultsType,
    CorrelationConfigType,
} from '~/types'
import { dayjs } from 'lib/dayjs'
import { combineUrl } from 'kea-router'
import { FunnelsQuery } from '~/queries/schema'
import { FunnelLayout } from 'lib/constants'
import { elementsToAction } from 'scenes/events/createActionFromEvent'
import { teamLogic } from 'scenes/teamLogic'
import { Noun } from '~/models/groupsModel'

/** Chosen via heuristics by eyeballing some values
 * Assuming a normal distribution, then 90% of values are within 1.5 standard deviations of the mean
 * which gives a ballpark of 1 highlighting every 10 breakdown values
 */
const DEVIATION_SIGNIFICANCE_MULTIPLIER = 1.5

const EMPTY_BREAKDOWN_KEY = '__empty_string__'
const EMPTY_BREAKDOWN_VALUE = '(empty string)'
export const EMPTY_BREAKDOWN_VALUES = {
    rowKey: EMPTY_BREAKDOWN_KEY,
    breakdown: [EMPTY_BREAKDOWN_KEY], // unique key not to be used by backend in calculating breakdowns
    breakdown_value: [EMPTY_BREAKDOWN_VALUE],
    isEmpty: true,
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

export function isBreakdownFunnelResults(results: FunnelResultType): results is FunnelStep[][] {
    return Array.isArray(results) && (results.length === 0 || Array.isArray(results[0]))
}

/** Breakdown parameter could be a string (property breakdown) or object/number (list of cohort ids). */
export function isValidBreakdownParameter(
    breakdown: BreakdownKeyType | undefined,
    breakdowns: Breakdown[] | undefined
): boolean {
    return (
        (Array.isArray(breakdowns) && breakdowns.length > 0) ||
        ['string', 'null', 'undefined', 'number'].includes(typeof breakdown) ||
        Array.isArray(breakdown)
    )
}

/** String identifier for breakdowns used when determining visibility. */
export function getVisibilityKey(breakdownValue?: BreakdownKeyType): string {
    const breakdownValues = getBreakdownStepValues(
        { breakdown: breakdownValue, breakdown_value: breakdownValue },
        -1
    ).breakdown_value
    return breakdownValues.join('::')
}

export const SECONDS_TO_POLL = 3 * 60

interface BreakdownStepValues {
    rowKey: string
    breakdown: (string | number)[]
    breakdown_value: (string | number)[]
    isEmpty?: boolean
}

export const getBreakdownStepValues = (
    breakdownStep: Pick<FunnelStep, 'breakdown' | 'breakdown_value'>,
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

export const isStepsEmpty = (filters: FunnelsFilterType): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0

export const isStepsUndefined = (filters: FunnelsFilterType): boolean =>
    typeof filters.events === 'undefined' && (typeof filters.actions === 'undefined' || filters.actions.length === 0)

export const deepCleanFunnelExclusionEvents = (filters: FunnelsFilterType): FunnelExclusion[] | undefined => {
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

const findFirstNumber = (candidates: (number | undefined)[]): number | undefined =>
    candidates.find((s) => typeof s === 'number')

export const getClampedStepRangeFilter = ({
    stepRange,
    filters,
}: {
    stepRange?: FunnelExclusion
    filters: FunnelsFilterType
}): FunnelExclusion => {
    const maxStepIndex = Math.max((filters.events?.length || 0) + (filters.actions?.length || 0) - 1, 1)

    let funnel_from_step = findFirstNumber([stepRange?.funnel_from_step, filters.funnel_from_step])
    let funnel_to_step = findFirstNumber([stepRange?.funnel_to_step, filters.funnel_to_step])

    const funnelFromStepIsSet = typeof funnel_from_step === 'number'
    const funnelToStepIsSet = typeof funnel_to_step === 'number'

    if (funnelFromStepIsSet && funnelToStepIsSet) {
        funnel_from_step = clamp(funnel_from_step ?? 0, 0, maxStepIndex)
        funnel_to_step = clamp(funnel_to_step ?? maxStepIndex, funnel_from_step + 1, maxStepIndex)
    }

    return {
        ...(stepRange || {}),
        funnel_from_step,
        funnel_to_step,
    }
}

export const getClampedStepRangeFilterDataExploration = ({
    stepRange,
    query,
}: {
    stepRange?: FunnelExclusion
    query: FunnelsQuery
}): FunnelExclusion => {
    const maxStepIndex = Math.max(query.series.length || 0 - 1, 1)

    let funnel_from_step = findFirstNumber([stepRange?.funnel_from_step, query.funnelsFilter?.funnel_from_step])
    let funnel_to_step = findFirstNumber([stepRange?.funnel_to_step, query.funnelsFilter?.funnel_to_step])

    const funnelFromStepIsSet = typeof funnel_from_step === 'number'
    const funnelToStepIsSet = typeof funnel_to_step === 'number'

    if (funnelFromStepIsSet && funnelToStepIsSet) {
        funnel_from_step = clamp(funnel_from_step ?? 0, 0, maxStepIndex)
        funnel_to_step = clamp(funnel_to_step ?? maxStepIndex, funnel_from_step + 1, maxStepIndex)
    }

    return {
        ...(stepRange || {}),
        funnel_from_step,
        funnel_to_step,
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

export function getIncompleteConversionWindowStartDate(
    window: FunnelConversionWindow,
    startDate: dayjs.Dayjs = dayjs()
): dayjs.Dayjs {
    const { funnel_window_interval, funnel_window_interval_unit } = window
    return startDate.subtract(funnel_window_interval, funnel_window_interval_unit)
}

export function generateBaselineConversionUrl(url?: string | null): string {
    if (!url) {
        return ''
    }
    const parsed = combineUrl(url)
    return combineUrl(parsed.url, { funnel_step_breakdown: undefined }).url
}

export function stepsWithConversionMetrics(
    steps: FunnelStepWithNestedBreakdown[],
    stepReference: FunnelStepReference
): FunnelStepWithConversionMetrics[] {
    const stepsWithConversionMetrics = steps.map((step, i) => {
        const previousCount = i > 0 ? steps[i - 1].count : step.count // previous is faked for the first step
        const droppedOffFromPrevious = Math.max(previousCount - step.count, 0)

        const nestedBreakdown = step.nested_breakdown?.map((breakdown, breakdownIndex) => {
            const firstBreakdownCount = steps[0]?.nested_breakdown?.[breakdownIndex].count || 0
            // firstBreakdownCount serves as previousBreakdownCount for the first step so that
            // "Relative to previous step" is shown correctly – later series use the actual previous steps
            const previousBreakdownCount =
                i === 0 ? firstBreakdownCount : steps[i - 1].nested_breakdown?.[breakdownIndex].count || 0
            const nestedDroppedOffFromPrevious = Math.max(previousBreakdownCount - breakdown.count, 0)
            const conversionRates = {
                fromPrevious: previousBreakdownCount === 0 ? 0 : breakdown.count / previousBreakdownCount,
                total: breakdown.count / firstBreakdownCount,
            }
            return {
                ...breakdown,
                droppedOffFromPrevious: nestedDroppedOffFromPrevious,
                conversionRates: {
                    ...conversionRates,
                    fromBasisStep:
                        stepReference === FunnelStepReference.total
                            ? conversionRates.total
                            : conversionRates.fromPrevious,
                },
            }
        })

        const conversionRatesTotal = step.count / steps[0].count
        const conversionRates = {
            fromPrevious: previousCount === 0 ? 0 : step.count / previousCount,

            // We get NaN from dividing 0/0 so we just show 0 instead
            // This is an empty funnel so dropped off percentage will show as 100%
            // and conversion percentage as 0% but that's better for users than `NaN%`
            total: Number.isNaN(conversionRatesTotal) ? 0 : conversionRatesTotal,
        }
        return {
            ...step,
            droppedOffFromPrevious,
            nested_breakdown: nestedBreakdown,
            conversionRates: {
                ...conversionRates,
                fromBasisStep:
                    i > 0
                        ? stepReference === FunnelStepReference.total
                            ? conversionRates.total
                            : conversionRates.fromPrevious
                        : conversionRates.total,
            },
        }
    })

    if (!stepsWithConversionMetrics.length || !stepsWithConversionMetrics[0].nested_breakdown) {
        return stepsWithConversionMetrics
    }

    return stepsWithConversionMetrics.map((step) => {
        // Per step breakdown significance
        const [meanFromPrevious, stdDevFromPrevious] = getMeanAndStandardDeviation(
            step.nested_breakdown?.map((item) => item.conversionRates.fromPrevious)
        )
        const [meanFromBasis, stdDevFromBasis] = getMeanAndStandardDeviation(
            step.nested_breakdown?.map((item) => item.conversionRates.fromBasisStep)
        )
        const [meanTotal, stdDevTotal] = getMeanAndStandardDeviation(
            step.nested_breakdown?.map((item) => item.conversionRates.total)
        )

        const isOutlier = (value: number, mean: number, stdDev: number): boolean => {
            return (
                value > mean + stdDev * DEVIATION_SIGNIFICANCE_MULTIPLIER ||
                value < mean - stdDev * DEVIATION_SIGNIFICANCE_MULTIPLIER
            )
        }

        const nestedBreakdown = step.nested_breakdown?.map((item) => {
            return {
                ...item,
                significant: {
                    fromPrevious: isOutlier(item.conversionRates.fromPrevious, meanFromPrevious, stdDevFromPrevious),
                    fromBasisStep: isOutlier(item.conversionRates.fromBasisStep, meanFromBasis, stdDevFromBasis),
                    total: isOutlier(item.conversionRates.total, meanTotal, stdDevTotal),
                },
            }
        })

        return {
            ...step,
            nested_breakdown: nestedBreakdown,
        }
    })
}

export function flattenedStepsByBreakdown(
    steps: FunnelStepWithConversionMetrics[],
    layout: FunnelLayout | undefined,
    disableBaseline: boolean,
    skipInitialRows: boolean = false
): FlattenedFunnelStepByBreakdown[] {
    // Initialize with two rows for rendering graph and header
    const flattenedStepsByBreakdown: FlattenedFunnelStepByBreakdown[] = skipInitialRows
        ? []
        : [{ rowKey: 'steps-meta' }, { rowKey: 'graph' }, { rowKey: 'table-header' }]

    if (steps.length > 0) {
        const baseStep = steps[0]
        const lastStep = steps[steps.length - 1]
        const hasBaseline =
            !baseStep.breakdown ||
            ((layout || FunnelLayout.vertical) === FunnelLayout.vertical &&
                (baseStep.nested_breakdown?.length ?? 0) > 1)
        // Baseline - total step to step metrics, only add if more than 1 breakdown or not breakdown
        if (hasBaseline && !disableBaseline) {
            flattenedStepsByBreakdown.push({
                ...getBreakdownStepValues(baseStep, 0, true),
                isBaseline: true,
                breakdownIndex: 0,
                steps: steps.map((s) => ({
                    ...s,
                    nested_breakdown: undefined,
                    breakdown_value: 'Baseline',
                    converted_people_url: generateBaselineConversionUrl(s.converted_people_url),
                    dropped_people_url: generateBaselineConversionUrl(s.dropped_people_url),
                })),
                conversionRates: {
                    total: (lastStep?.count ?? 0) / (baseStep?.count ?? 1),
                },
            })
        }
        // Per Breakdown
        if (baseStep.nested_breakdown?.length) {
            baseStep.nested_breakdown.forEach((breakdownStep, i) => {
                const stepsInBreakdown = steps
                    .filter((s) => !!s?.nested_breakdown?.[i])
                    .map((s) => s.nested_breakdown?.[i] as FunnelStepWithConversionMetrics)
                const offset = hasBaseline ? 1 : 0
                flattenedStepsByBreakdown.push({
                    ...getBreakdownStepValues(breakdownStep, i + offset),
                    isBaseline: false,
                    breakdownIndex: i + offset,
                    steps: stepsInBreakdown,
                    conversionRates: {
                        total:
                            (stepsInBreakdown[stepsInBreakdown.length - 1]?.count ?? 0) /
                            (stepsInBreakdown[0]?.count ?? 1),
                    },
                    significant: stepsInBreakdown.some(
                        (step) => step.significant?.total || step.significant?.fromPrevious
                    ),
                })
            })
        }
    }
    return flattenedStepsByBreakdown
}

/**
 * Transform pre-#12113 funnel series keys to the current more reliable format.
 *
 * Old: `${step.type}/${step.action_id}/${step.order}/${breakdownValues.join('_')}`
 * New: `breakdownValues.join('::')`
 *
 * If you squint you'll notice this doesn't actually handle the .join() part, but that's fine,
 * because that's only relevant for funnels with multiple breakdowns, and that hasn't been
 * released to users at the point of the format change.
 */
export const transformLegacyHiddenLegendKeys = (
    hidden_legend_keys: Record<string, boolean | undefined>
): Record<string, boolean | undefined> => {
    const hiddenLegendKeys: Record<string, boolean | undefined> = {}
    for (const [key, value] of Object.entries(hidden_legend_keys)) {
        const oldFormatMatch = key.match(/\w+\/.+\/\d+\/(.+)/)
        if (oldFormatMatch) {
            // Don't override values for series if already set from a previously-seen old-format key
            if (!(oldFormatMatch[1] in hiddenLegendKeys)) {
                hiddenLegendKeys[oldFormatMatch[1]] = value
            }
        } else {
            hiddenLegendKeys[key] = value
        }
    }
    return hiddenLegendKeys
}

export const parseBreakdownValue = (
    item: string
): {
    breakdown: string
    breakdown_value: string
} => {
    const components = item.split('::')
    if (components.length === 1) {
        return { breakdown: components[0], breakdown_value: '' }
    } else {
        return {
            breakdown: components[0],
            breakdown_value: components[1],
        }
    }
}

export const parseEventAndProperty = (
    event: FunnelCorrelation['event']
): {
    name: string
    properties?: AnyPropertyFilter[]
} => {
    const components = event.event.split('::')
    /*
      The `event` is either an event name, or event::property::property_value
    */
    if (components.length === 1) {
        return { name: components[0] }
    } else if (components[0] === '$autocapture') {
        // We use elementsToAction to generate the required property filters
        const elementData = elementsToAction(event.elements)
        return {
            name: components[0],
            properties: Object.entries(elementData)
                .filter(([, propertyValue]) => !!propertyValue)
                .map(([propertyKey, propertyValue]) => ({
                    key: propertyKey as ElementPropertyFilter['key'],
                    operator: PropertyOperator.Exact,
                    type: PropertyFilterType.Element,
                    value: [propertyValue as string],
                })),
        }
    } else {
        return {
            name: components[0],
            properties: [
                {
                    key: components[1],
                    operator: PropertyOperator.Exact,
                    value: components[2],
                    type: PropertyFilterType.Event,
                },
            ],
        }
    }
}

export const parseDisplayNameForCorrelation = (
    record: FunnelCorrelation
): { first_value: string; second_value?: string } => {
    let first_value = undefined
    let second_value = undefined
    const values = record.event.event.split('::')

    if (record.result_type === FunnelCorrelationResultsType.Events) {
        first_value = record.event.event
        return { first_value, second_value }
    } else if (record.result_type === FunnelCorrelationResultsType.Properties) {
        first_value = values[0]
        second_value = values[1]
        return { first_value, second_value }
    } else if (values[0] === '$autocapture' && values[1] === 'elements_chain') {
        // special case for autocapture elements_chain
        first_value = autoCaptureEventToDescription({
            ...record.event,
            event: '$autocapture',
        }) as string
        return { first_value, second_value }
    } else {
        // FunnelCorrelationResultsType.EventWithProperties
        // Events here come in the form of event::property::value
        return { first_value: values[1], second_value: values[2] }
    }
}

export const appendToCorrelationConfig = (
    configKey: keyof CorrelationConfigType,
    currentValue: string[],
    configValue: string
): void => {
    // Helper to handle updating correlationConfig within the Team model. Only
    // handles further appending to current values.

    // When we exclude a property, we want to update the config stored
    // on the current Team/Project.
    const oldCurrentTeam = teamLogic.values.currentTeam

    // If we haven't actually retrieved the current team, we can't
    // update the config.
    if (oldCurrentTeam === null || !currentValue) {
        console.warn('Attempt to update correlation config without first retrieving existing config')
        return
    }

    const oldCorrelationConfig = oldCurrentTeam.correlation_config

    const configList = [...Array.from(new Set(currentValue.concat([configValue])))]

    const correlationConfig = {
        ...oldCorrelationConfig,
        [configKey]: configList,
    }

    teamLogic.actions.updateCurrentTeam({
        correlation_config: correlationConfig,
    })
}

export function aggregationLabelForHogQL(funnel_aggregate_by_hogql: string): Noun {
    if (funnel_aggregate_by_hogql === 'person_id') {
        return { singular: 'person', plural: 'persons' }
    }
    if (funnel_aggregate_by_hogql === 'properties.$session_id') {
        return { singular: 'session', plural: 'sessions' }
    }
    return { singular: 'result', plural: 'results' }
}

import { FunnelLayout } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { formatDateRange } from 'lib/utils/datetime'
import { humanFriendlyDuration } from 'lib/utils/durations'
import { autoCaptureEventToDescription } from 'lib/utils/events'
import { clamp, percentage } from 'lib/utils/numbers'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { elementsToAction } from 'scenes/activity/explore/createActionFromEvent'
import { teamLogic } from 'scenes/teamLogic'

import { Noun } from '~/models/groupsModel'
import {
    AnyEntityNode,
    BreakdownFilter,
    FunnelExclusionSteps,
    FunnelsDataWarehouseNode,
    FunnelsFilter,
    FunnelsQuery,
} from '~/queries/schema/schema-general'
import { integer } from '~/queries/schema/type-utils'
import { isFunnelsDataWarehouseNode } from '~/queries/utils'
import {
    AnyPropertyFilter,
    Breakdown,
    BreakdownKeyType,
    CorrelationConfigType,
    ElementPropertyFilter,
    FlattenedFunnelStepByBreakdown,
    FunnelConversionWindow,
    FunnelConversionWindowTimeUnit,
    FunnelCorrelation,
    FunnelCorrelationResultsType,
    FunnelResultType,
    FunnelStep,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    PropertyFilterType,
    PropertyOperator,
} from '~/types'

export const TIME_INTERVAL_BOUNDS: Record<FunnelConversionWindowTimeUnit, number[]> = {
    [FunnelConversionWindowTimeUnit.Second]: [1, 3600],
    [FunnelConversionWindowTimeUnit.Minute]: [1, 1440],
    [FunnelConversionWindowTimeUnit.Hour]: [1, 24],
    [FunnelConversionWindowTimeUnit.Day]: [1, 365],
    [FunnelConversionWindowTimeUnit.Week]: [1, 53],
    [FunnelConversionWindowTimeUnit.Month]: [1, 12],
}

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

const calculateAverageConversionTime = (breakdown_results: FunnelStepWithNestedBreakdown[]): number | null => {
    const resultsWithAverage = breakdown_results.filter((r) => r.average_conversion_time != null)
    const totalCount = resultsWithAverage.reduce((sum, r) => sum + r.count, 0)
    const weightedSum = resultsWithAverage.reduce((sum, r) => sum + r.average_conversion_time! * r.count, 0)
    return totalCount > 0 ? weightedSum / totalCount : null
}

export function aggregateBreakdownResult(
    results: FunnelStep[][],
    breakdownProperty?: BreakdownKeyType
): FunnelStepWithNestedBreakdown[] {
    if (results.length) {
        // Create mapping to determine breakdown ordering by first step counts
        const breakdownToOrderMap: Record<string | number, FunnelStep> = results
            .reduce<{ breakdown_value: (string | number)[]; count: number }[]>((allEntries, breakdownSteps) => {
                allEntries.push({
                    breakdown_value: getBreakdownStepValues(breakdownSteps?.[0], -1).breakdown_value,
                    count: breakdownSteps?.[0]?.count ?? 0,
                })
                return allEntries
            }, [])
            .sort((a, b) => b.count - a.count)
            .reduce(
                (allEntries, breakdown, order) =>
                    Object.assign(allEntries, {
                        [breakdown.breakdown_value.join('_')]: { ...breakdown, order },
                    }),
                {}
            )

        return results[0].map((step, i) => {
            const breakdownResults = results
                .reduce((allEntries, breakdownSteps) => {
                    allEntries.push({
                        ...breakdownSteps[i],
                        order: breakdownToOrderMap[
                            getBreakdownStepValues(breakdownSteps[i], i).breakdown_value.join('_')
                        ].order,
                    })
                    return allEntries
                }, [])
                .sort((a, b) => a.order - b.order)

            return {
                ...step,
                count: results.reduce((total, breakdownSteps) => total + breakdownSteps[i].count, 0),
                breakdown: breakdownProperty,
                nested_breakdown: breakdownResults,
                average_conversion_time: calculateAverageConversionTime(breakdownResults),
                // we can't compute the median, as we don't have the distribution of conversion times
                median_conversion_time: null,
                people: [],
            }
        })
    }
    return []
}

export function isBreakdownFunnelResults(results: FunnelResultType): results is FunnelStep[][] {
    return Array.isArray(results) && (results.length === 0 || Array.isArray(results[0]))
}

/** Whether a STEPS result is a compare-tagged flat list (both periods' steps tagged with
 * `compare_label`, no breakdown). Breakdown + compare is a list-of-lists — see
 * `isFunnelStepsBreakdownCompareResult`. */
export function isFunnelStepsCompareResult(results: FunnelResultType): results is FunnelStep[] {
    return (
        Array.isArray(results) &&
        results.length > 0 &&
        !Array.isArray(results[0]) &&
        (results as FunnelStep[]).some((step) => step.compare_label != null)
    )
}

/** Whether a STEPS result is a breakdown + compare result — a list of inner funnels (one per
 * breakdown value, per period) whose steps carry `compare_label`. The runner emits 2·N such inner
 * funnels; `aggregateBreakdownCompareResult` pairs them by breakdown value. */
export function isFunnelStepsBreakdownCompareResult(results: FunnelResultType): results is FunnelStep[][] {
    return (
        isBreakdownFunnelResults(results) &&
        results.length > 0 &&
        (results[0] as FunnelStep[]).some((step) => step.compare_label != null)
    )
}

const COMPARE_TO_UNIT: Record<string, dayjs.ManipulateType> = {
    h: 'hour',
    d: 'day',
    w: 'week',
    m: 'month',
    y: 'year',
}

function parseCompareToOffset(
    compareTo: string | null | undefined
): { amount: number; unit: dayjs.ManipulateType } | null {
    const match = compareTo?.match(/^-?(\d+)([hdwmy])$/)
    return match ? { amount: parseInt(match[1], 10), unit: COMPARE_TO_UNIT[match[2]] } : null
}

/**
 * Human-friendly date range for a funnel compare period, derived from the resolved current range
 * plus the compare offset — the frontend mirror of the backend's previous-period shifting (the
 * merged response only carries the current period's resolved range). Returns null when the range
 * is unavailable.
 */
export function funnelComparePeriodDateRange(
    compareLabel: 'current' | 'previous',
    resolvedDateRange: { date_from?: string | null; date_to?: string | null } | null | undefined,
    compareTo?: string | null
): string | null {
    const from = resolvedDateRange?.date_from ? dayjs(resolvedDateRange.date_from) : null
    const to = resolvedDateRange?.date_to ? dayjs(resolvedDateRange.date_to) : null
    if (!from || !to || !from.isValid() || !to.isValid()) {
        return null
    }
    if (compareLabel === 'current') {
        return formatDateRange(from, to)
    }
    const offset = parseCompareToOffset(compareTo)
    if (offset) {
        return formatDateRange(from.subtract(offset.amount, offset.unit), to.subtract(offset.amount, offset.unit))
    }
    // Default previous period: the equal-length window ending the day before the current window.
    const previousTo = from.subtract(1, 'day')
    const previousFrom = previousTo.subtract(to.diff(from, 'day'), 'day')
    return formatDateRange(previousFrom, previousTo)
}

/** Compose the funnel tooltip header from the parts a series carries: its breakdown value, its
 * compare period (optionally with a date range), or both joined — so breakdown + compare bars are
 * labelled with both which value and which period they represent. */
export function funnelTooltipHeaderLabel({
    breakdownLabel,
    compareLabel,
    comparePeriodDateRange,
}: {
    breakdownLabel?: string | null
    compareLabel?: 'current' | 'previous'
    comparePeriodDateRange?: string | null
}): string {
    const periodLabel = compareLabel
        ? `${compareLabel === 'current' ? 'Current' : 'Previous'}${
              comparePeriodDateRange ? ` (${comparePeriodDateRange})` : ''
          }`
        : null
    return [breakdownLabel || null, periodLabel].filter(Boolean).join(' • ')
}

/** Desaturate a series color to the "previous period" treatment (50% opacity), matching the
 * dimmed previous-period series in trends (`LineGraph.processDataset`). */
export function dimPreviousPeriodColor(color: string): string {
    // Only plain 6-digit hex gets an alpha suffix; anything already carrying alpha or a
    // non-hex format is left untouched.
    return /^#[0-9a-fA-F]{6}$/.test(color) ? `${color}80` : color
}

/**
 * Reshape a compare-tagged flat STEPS result into one step per order, each carrying a
 * `nested_breakdown` of `[currentSeries, previousSeries]`. This reuses the breakdown rendering
 * path (`StepBars` draws one bar per `nested_breakdown` entry) to draw two grouped bars per step.
 * The series keep their `compare_label` so the previous bar can be desaturated and the tooltip
 * labelled by period.
 */
export function aggregateFunnelCompareResult(results: FunnelStep[]): FunnelStepWithNestedBreakdown[] {
    const current = results.filter((step) => step.compare_label === 'current').sort((a, b) => a.order - b.order)
    const previous = results.filter((step) => step.compare_label === 'previous').sort((a, b) => a.order - b.order)

    return current.map((step, i) => ({
        ...step,
        // Both bars keep the step's `order` so they share the step's color (funnel bars are colored
        // per step); the previous bar is then dimmed via its `compare_label`. The array position
        // (current first, previous second) is what `stepsWithConversionMetrics` uses for per-period
        // conversion rates, and `StepBars` keys the bars on `compare_label`.
        nested_breakdown: [{ ...step }, ...(previous[i] ? [{ ...previous[i] }] : [])],
    }))
}

/**
 * Reshape a breakdown + compare STEPS result (2·N inner funnels — one per breakdown value, per
 * period) into one step per order, each carrying a `nested_breakdown` that pairs the current and
 * previous bar for every breakdown value: `[A_current, A_previous, B_current, B_previous, …]`.
 *
 * Both bars of a value share an `order` so they resolve to the same breakdown color (the previous
 * one is then desaturated via its `compare_label`), while distinct values get distinct orders and
 * colors. Values are ordered by current first-step count descending, matching the non-compare
 * breakdown path.
 */
export function aggregateBreakdownCompareResult(
    results: FunnelStep[][],
    breakdownProperty?: BreakdownKeyType
): FunnelStepWithNestedBreakdown[] {
    const groups = results.filter((group) => group.length > 0)
    if (!groups.length) {
        return []
    }

    const valueKey = (group: FunnelStep[]): string => getBreakdownStepValues(group[0], -1).breakdown_value.join('_')

    const currentByValue = new Map<string, FunnelStep[]>()
    const previousByValue = new Map<string, FunnelStep[]>()
    for (const group of groups) {
        const target = group[0].compare_label === 'previous' ? previousByValue : currentByValue
        target.set(valueKey(group), group)
    }

    // Union of breakdown values across periods, ordered by current first-step count descending
    // (falling back to the previous period's count for values that only appear there).
    const firstStepCount = (key: string): number =>
        currentByValue.get(key)?.[0]?.count ?? previousByValue.get(key)?.[0]?.count ?? 0
    const orderedValues = Array.from(new Set(groups.map(valueKey))).sort(
        (a, b) => firstStepCount(b) - firstStepCount(a)
    )

    const representative = groups[0]

    return representative.map((baseStep, stepIndex) => {
        const nestedBreakdown: FunnelStep[] = []
        let currentTotal = 0

        orderedValues.forEach((key, breakdownOrder) => {
            const current = currentByValue.get(key)?.[stepIndex]
            const previous = previousByValue.get(key)?.[stepIndex]
            if (current) {
                nestedBreakdown.push({ ...current, order: breakdownOrder })
                currentTotal += current.count
            }
            if (previous) {
                nestedBreakdown.push({ ...previous, order: breakdownOrder })
            }
        })

        return {
            ...baseStep,
            count: currentTotal,
            breakdown: breakdownProperty,
            nested_breakdown: nestedBreakdown,
            average_conversion_time: calculateAverageConversionTime(
                nestedBreakdown.filter((variant) => variant.compare_label !== 'previous')
            ),
            median_conversion_time: null,
            people: [],
        }
    })
}

/** Breakdown parameter could be a string (property breakdown) or object/number (list of cohort ids). */
export function hasBreakdownFilterParameter(
    breakdown: BreakdownKeyType | undefined,
    breakdowns: Breakdown[] | undefined
): boolean {
    return (
        (Array.isArray(breakdowns) && breakdowns.length > 0) ||
        ['string', 'null', 'undefined', 'number'].includes(typeof breakdown) ||
        Array.isArray(breakdown)
    )
}

/**
 * Whether a series's `breakdown_value` represents an actual user-picked breakdown.
 * The funnel backend uses the literal "Baseline" (or `['Baseline', ...]` for
 * multi-breakdowns) to mark the overall, non-broken-down series.
 */
export function hasBreakdown(breakdownValue: BreakdownKeyType | undefined): boolean {
    return (
        breakdownValue !== undefined &&
        breakdownValue !== 'Baseline' &&
        !(Array.isArray(breakdownValue) && breakdownValue[0] === 'Baseline')
    )
}

/**
 * Aggregate "conversion so far" (across all breakdown values) to show alongside a hovered breakdown
 * variant's own conversion. Returns null unless `series` is a genuine breakdown variant of `step` —
 * excluding the top-level step itself, compare-only bars, and breakdown+compare (the aggregate spans
 * periods there and would be ambiguous).
 */
export function getFunnelAggregateConversionRate(
    series: FunnelStepWithConversionMetrics,
    step: FunnelStepWithConversionMetrics
): number | null {
    return series !== step && hasBreakdown(series.breakdown_value) && !series.compare_label
        ? step.conversionRates.total
        : null
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
        breakdownStep.breakdown_value === 'Baseline' ||
        (Array.isArray(breakdownStep.breakdown_value) && breakdownStep.breakdown_value[0] === 'Baseline')
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

export const getClampedFunnelStepRange = (
    stepRange: FunnelExclusionSteps | FunnelsFilter,
    series: AnyEntityNode<FunnelsDataWarehouseNode>[] | null | undefined
): { funnelFromStep?: integer; funnelToStep?: integer } => {
    const maxStepIndex = Math.max((series?.length || 0) - 1, 1)
    const { funnelFromStep, funnelToStep } = stepRange

    return {
        ...(funnelFromStep != null ? { funnelFromStep: clamp(funnelFromStep, 0, maxStepIndex - 1) } : {}),
        ...(funnelToStep != null ? { funnelToStep: clamp(funnelToStep, (funnelFromStep || 0) + 1, maxStepIndex) } : {}),
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
    const { funnelWindowInterval = 14, funnelWindowIntervalUnit } = window
    return startDate.subtract(funnelWindowInterval, funnelWindowIntervalUnit)
}

export function stepsWithConversionMetrics(
    steps: FunnelStepWithNestedBreakdown[],
    stepReference: FunnelStepReference,
    optionalSteps: number[] = []
): FunnelStepWithConversionMetrics[] {
    const compareBars = steps[0]?.nested_breakdown
    const isCompare = compareBars?.some((b) => b.compare_label != null) ?? false
    // Compare bars are sized per period, not per breakdown value. Within a period every value keeps its
    // own conversion from its own first step — so at the first step all of a period's values share one
    // height — and the whole period is then scaled by its share of the larger period's total entrants.
    // The larger period fills the bar (100%); the smaller one is proportionally shorter, its missing
    // volume left as a blank gap above. Applied below as (count * periodTotal) / (firstStep * basis) —
    // a single division so the exact ratios stay clean. Pure compare has one value whose first step is
    // the period total, so it collapses to count / max(current, previous).
    let currentTotal = 0
    let previousTotal = 0
    let compareBasis = 0
    if (isCompare && compareBars) {
        for (const bar of compareBars) {
            if (bar.compare_label === 'previous') {
                previousTotal += bar.count
            } else {
                currentTotal += bar.count
            }
        }
        compareBasis = Math.max(currentTotal, previousTotal, 0)
    }

    let lastNonOptionalStep = 0
    const stepsWithConversionMetrics = steps.map((step, i) => {
        // Use lastNonOptionalStep for previousCount calculation (this is the last non-optional step we've seen)
        const previousStepIndex = i > 0 ? lastNonOptionalStep : 0
        const previousCount = i > 0 ? steps[previousStepIndex].count : step.count // previous is faked for the first step
        const droppedOffFromPrevious = Math.max(previousCount - step.count, 0)

        const nestedBreakdown = step.nested_breakdown?.map((breakdown, breakdownIndex) => {
            const firstBreakdownCount = steps[0]?.nested_breakdown?.[breakdownIndex].count || 0
            // firstBreakdownCount serves as previousBreakdownCount for the first step so that
            // "Relative to previous step" is shown correctly – later series use the actual previous steps
            const previousBreakdownCount =
                i === 0 ? firstBreakdownCount : steps[previousStepIndex].nested_breakdown?.[breakdownIndex].count || 0
            const nestedDroppedOffFromPrevious = Math.max(previousBreakdownCount - breakdown.count, 0)
            const conversionRates = {
                fromPrevious: previousBreakdownCount === 0 ? 0 : breakdown.count / previousBreakdownCount,
                total: firstBreakdownCount === 0 ? 0 : breakdown.count / firstBreakdownCount,
            }
            return {
                ...breakdown,
                droppedOffFromPrevious: nestedDroppedOffFromPrevious,
                conversionRates: {
                    ...conversionRates,
                    fromBasisStep: isCompare
                        ? firstBreakdownCount > 0 && compareBasis > 0
                            ? (breakdown.count *
                                  (breakdown.compare_label === 'previous' ? previousTotal : currentTotal)) /
                              (firstBreakdownCount * compareBasis)
                            : 0
                        : stepReference === FunnelStepReference.total
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

        // Update lastNonOptionalStep after processing this step, so it's available for the next iteration
        // Note: optionalSteps are 1-indexed, so we convert to 0-indexed
        if (!optionalSteps.includes(i + 1)) {
            lastNonOptionalStep = i
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
                })),
                conversionRates: {
                    total: (lastStep?.count || 0) / (baseStep?.count || 1),
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
 * Build the detailed-results rows for a pure compare STEPS funnel (no breakdown): one baseline row
 * per period. Rows keep `breakdown_value` undefined so their customization key and color position
 * match the chart's compare bars — the pair shares one color token and the previous row is dimmed
 * via its `compare_label`, not a separate token.
 */
export function flattenedStepsByCompare(steps: FunnelStepWithConversionMetrics[]): FlattenedFunnelStepByBreakdown[] {
    const periodCount = steps[0]?.nested_breakdown?.length ?? 0
    const rows: FlattenedFunnelStepByBreakdown[] = []
    for (let i = 0; i < periodCount; i++) {
        const stepsInPeriod = steps
            .filter((s) => !!s?.nested_breakdown?.[i])
            .map((s) => s.nested_breakdown?.[i] as FunnelStepWithConversionMetrics)
        const compareLabel = stepsInPeriod[0]?.compare_label ?? (i === 0 ? 'current' : 'previous')
        rows.push({
            rowKey: `baseline_${compareLabel}`,
            isBaseline: true,
            breakdownIndex: i,
            colorIndex: 0,
            compare_label: compareLabel,
            steps: stepsInPeriod,
            conversionRates: {
                total: (stepsInPeriod[stepsInPeriod.length - 1]?.count ?? 0) / (stepsInPeriod[0]?.count ?? 1),
            },
        })
    }
    return rows
}

/**
 * Build the detailed-results rows for a breakdown × compare STEPS funnel: interleaved
 * current/previous row pairs per breakdown value, preceded by a per-period baseline pair when the
 * baseline is shown (vertical layout with more than one value — the same rule as plain breakdowns).
 * Both rows of a pair share a `colorIndex` so they resolve to one color token (previous dimmed).
 */
export function flattenedStepsByBreakdownCompare(
    steps: FunnelStepWithConversionMetrics[],
    layout: FunnelLayout | undefined,
    disableBaseline: boolean
): FlattenedFunnelStepByBreakdown[] {
    const rows: FlattenedFunnelStepByBreakdown[] = []
    const entries = steps[0]?.nested_breakdown ?? []
    if (!entries.length) {
        return rows
    }

    // Entries of one value share an `order` (see `aggregateBreakdownCompareResult`), so the value
    // count is the highest order + 1.
    const valueCount = Math.max(...entries.map((entry) => entry.order ?? 0)) + 1
    const hasBaseline = (layout || FunnelLayout.vertical) === FunnelLayout.vertical && valueCount > 1

    if (hasBaseline && !disableBaseline) {
        // Top-level steps already aggregate the current period (see `aggregateBreakdownCompareResult`);
        // the compare label is inherited from whichever period happened to come first, so set it explicitly.
        const currentBaselineSteps = steps.map((s) => ({
            ...s,
            nested_breakdown: undefined,
            breakdown_value: 'Baseline',
            compare_label: 'current' as const,
        }))
        // No previous-period aggregate exists upstream — synthesize one from the previous bars and
        // reuse the standard conversion math. This pass omits optional steps, so with optional steps
        // the previous baseline's `fromPrevious` references the immediately preceding step rather
        // than the last non-optional one.
        const previousBaselineSteps = stepsWithConversionMetrics(
            steps.map((s) => {
                const previousEntries = s.nested_breakdown?.filter((b) => b.compare_label === 'previous') ?? []
                return {
                    ...s,
                    count: previousEntries.reduce((sum, b) => sum + b.count, 0),
                    average_conversion_time: calculateAverageConversionTime(previousEntries),
                    median_conversion_time: null,
                    nested_breakdown: undefined,
                    breakdown_value: 'Baseline',
                    compare_label: 'previous' as const,
                }
            }),
            FunnelStepReference.total
        )
        for (const baselineSteps of [currentBaselineSteps, previousBaselineSteps]) {
            const compareLabel = baselineSteps[0].compare_label
            rows.push({
                ...getBreakdownStepValues(baselineSteps[0], 0, true),
                rowKey: `baseline_0_${compareLabel}`,
                isBaseline: true,
                breakdownIndex: rows.length,
                colorIndex: 0,
                compare_label: compareLabel,
                steps: baselineSteps,
                conversionRates: {
                    total: (baselineSteps[baselineSteps.length - 1]?.count ?? 0) / (baselineSteps[0]?.count || 1),
                },
            })
        }
    }

    // The offset follows `hasBaseline` regardless of `disableBaseline`, mirroring
    // `flattenedStepsByBreakdown`, so color positions stay stable when the baseline is suppressed.
    const baselineOffset = hasBaseline ? 1 : 0
    entries.forEach((entry, entryIndex) => {
        const stepsInSeries = steps
            .filter((s) => !!s?.nested_breakdown?.[entryIndex])
            .map((s) => s.nested_breakdown?.[entryIndex] as FunnelStepWithConversionMetrics)
        rows.push({
            ...getBreakdownStepValues(entry, rows.length),
            isBaseline: false,
            breakdownIndex: rows.length,
            colorIndex: (entry.order ?? 0) + baselineOffset,
            compare_label: entry.compare_label,
            steps: stepsInSeries,
            conversionRates: {
                total: (stepsInSeries[stepsInSeries.length - 1]?.count ?? 0) / (stepsInSeries[0]?.count ?? 1),
            },
            significant: stepsInSeries.some((step) => step.significant?.total || step.significant?.fromPrevious),
        })
    })

    return rows
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
    }
    return {
        breakdown: components[0],
        breakdown_value: components[1],
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
    }
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
        })
        return { first_value, second_value }
    }
    // FunnelCorrelationResultsType.EventWithProperties
    // Events here come in the form of event::property::value
    return { first_value: values[1], second_value: values[2] }
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

    const configList = Array.from(new Set(currentValue.concat([configValue])))

    const correlationConfig = {
        ...oldCorrelationConfig,
        [configKey]: configList,
    }

    teamLogic.actions.updateCurrentTeam({
        correlation_config: correlationConfig,
    })
}

export function aggregationLabelForHogQL(funnelAggregateByHogQL: string): Noun {
    if (funnelAggregateByHogQL === 'person_id') {
        return { singular: 'person', plural: 'persons' }
    }
    if (funnelAggregateByHogQL === 'properties.$session_id') {
        return { singular: 'session', plural: 'sessions' }
    }
    return { singular: 'result', plural: 'results' }
}

export function formatConvertedCount(step: FunnelStepWithConversionMetrics, aggregationTargetLabel: Noun): string {
    return pluralize(step.count ?? 0, aggregationTargetLabel.singular, aggregationTargetLabel.plural)
}

export function formatDroppedOffCount(step: FunnelStepWithConversionMetrics, aggregationTargetLabel: Noun): string {
    return pluralize(step.droppedOffFromPrevious ?? 0, aggregationTargetLabel.singular, aggregationTargetLabel.plural)
}

export function formatConvertedPercentage(step: FunnelStepWithConversionMetrics): string {
    return percentage(step.conversionRates.fromBasisStep, 2)
}

export function formatDroppedOffPercentage(step: FunnelStepWithConversionMetrics): string {
    return percentage(1 - step.conversionRates.fromBasisStep, 2)
}

export function formatMedianConversionTime(step: FunnelStepWithConversionMetrics): string {
    return humanFriendlyDuration(step.median_conversion_time, { maxUnits: 3 }) || '-'
}

export function getTooltipTitleForConverted(
    funnelsFilter: FunnelsFilter | null | undefined,
    aggregationTargetLabel: Noun,
    stepIndex: number
): JSX.Element {
    return (
        <>
            {capitalizeFirstLetter(aggregationTargetLabel.plural)} who completed this step
            {stepIndex > 0 && (
                <>
                    ,<br />
                    with conversion rate relative to the{' '}
                    {funnelsFilter?.funnelStepReference === FunnelStepReference.previous ? 'previous' : 'first'} step
                </>
            )}
        </>
    )
}

export function getTooltipTitleForDroppedOff(
    funnelsFilter: FunnelsFilter | null | undefined,
    aggregationTargetLabel: Noun
): JSX.Element {
    return (
        <>
            {capitalizeFirstLetter(aggregationTargetLabel.plural)} who didn't complete this step,
            <br />
            with drop-off rate relative to the{' '}
            {funnelsFilter?.funnelStepReference === FunnelStepReference.previous ? 'previous' : 'first'} step
        </>
    )
}

// Returns the single visible breakdown series on a funnel step, when the step is rendered
// with the non-breakdown layout but a breakdown filter is set. Lets callers route clicks
// through `openPersonsModalForSeries` so the persons modal is scoped to that value.
export function getStepBreakdownSeries(
    step: Pick<FunnelStepWithConversionMetrics, 'nested_breakdown'>,
    breakdownFilter: BreakdownFilter | null | undefined
): FunnelStepWithConversionMetrics | null {
    if (!breakdownFilter?.breakdown) {
        return null
    }

    if (!Array.isArray(step.nested_breakdown) || step.nested_breakdown.length !== 1) {
        return null
    }

    const single = step.nested_breakdown[0]
    if (!single || single.breakdown_value == null) {
        return null
    }

    return single
}

export function isFunnelWithEnoughSteps(series: FunnelsQuery['series'] | null | undefined): boolean {
    return (series?.length || 0) > 1
}

export function isFunnelWithIncompleteDataWarehouseStep(series: FunnelsQuery['series'] | null | undefined): boolean {
    return (series || []).some(
        (step) =>
            isFunnelsDataWarehouseNode(step) &&
            (!step.table_name || !step.id_field || !step.timestamp_field || !step.aggregation_target_field)
    )
}

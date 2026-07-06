import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { DataColorTheme, DataColorToken } from 'lib/colors'
import { BIN_COUNT_AUTO } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { average, percentage, sum } from 'lib/utils/numbers'
import { dashboardLogic } from 'scenes/dashboard/dashboardLogic'
import { getColorFromToken } from 'scenes/dataThemeLogic'
import { AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE } from 'scenes/insights/filters/aggregationTargetUtils'
import { insightDataLogic } from 'scenes/insights/insightDataLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'
import { getFunnelDatasetKey, getFunnelResultCustomizationColorToken } from 'scenes/insights/utils'

import { Noun, groupsModel } from '~/models/groupsModel'
import { seriesNodeToFilter } from '~/queries/nodes/InsightQuery/utils/queryNodeToFilter'
import { FunnelExclusionSteps, InsightQueryNode } from '~/queries/schema/schema-general'
import { FunnelsFilter, FunnelsQuery, FunnelsQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { isFunnelsQuery, isWebOverviewQuery, isWebStatsTableQuery } from '~/queries/utils'
import {
    FlattenedFunnelStepByBreakdown,
    EntityType,
    FunnelConversionWindow,
    FunnelConversionWindowTimeUnit,
    FunnelResultType,
    FunnelStepReference,
    FunnelStepWithConversionMetrics,
    FunnelStepWithNestedBreakdown,
    FunnelTimeConversionMetrics,
    FunnelVizType,
    FunnelsTimeConversionBins,
    HistogramGraphDatum,
    InsightLogicProps,
    InsightModel,
    InsightType,
    StepOrderValue,
    TrendResult,
    FilterType,
} from '~/types'

import type { funnelDataLogicType } from './funnelDataLogicType'
import {
    TIME_INTERVAL_BOUNDS,
    aggregateBreakdownCompareResult,
    aggregateBreakdownResult,
    aggregateFunnelCompareResult,
    aggregationLabelForHogQL,
    dimPreviousPeriodColor,
    flattenedStepsByBreakdown,
    flattenedStepsByBreakdownCompare,
    flattenedStepsByCompare,
    getIncompleteConversionWindowStartDate,
    getLastFilledStep,
    getReferenceStep,
    getVisibilityKey,
    isBreakdownFunnelResults,
    isFunnelStepsBreakdownCompareResult,
    isFunnelStepsCompareResult,
    isFunnelWithEnoughSteps,
    isFunnelWithIncompleteDataWarehouseStep,
    stepsWithConversionMetrics,
} from './funnelUtils'

const DEFAULT_FUNNEL_LOGIC_KEY = 'default_funnel_key'

/** A time-to-convert bins payload tagged with its compare period (present only when comparing). */
type TimeToConvertCompareBins = FunnelsTimeConversionBins & { compare_label?: 'current' | 'previous' }

/** Maps a time-to-convert bins payload onto histogram data. Returns null for too-few bins, [] when
 * nobody converted. Shared between the current and previous (compare) periods. */
function timeConversionBinsToHistogramData(
    timeConversionResults: FunnelsTimeConversionBins | null
): HistogramGraphDatum[] | null {
    if ((timeConversionResults?.bins?.length ?? 0) < 2) {
        return null // There are no results
    }

    const totalCount = sum(timeConversionResults!.bins.map(([, count]) => count))
    if (totalCount === 0) {
        return [] // Nobody has converted in the time period
    }

    const binSize = timeConversionResults!.bins[1][0] - timeConversionResults!.bins[0][0]
    return timeConversionResults!.bins.map(([id, count]: [id: number, count: number]) => {
        const value = Math.max(0, id)
        const percent = count / totalCount
        return {
            id: value,
            bin0: value,
            bin1: value + binSize,
            count,
            label: percent === 0 ? '' : percentage(percent, 1, true),
        }
    })
}

function getStepMetric(step: FunnelStepWithConversionMetrics | undefined, metric: string): number {
    if (!step) {
        return 0
    }
    switch (metric) {
        case 'conversion':
            return step.count ?? 0
        case 'dropoff':
            return step.droppedOffFromPrevious ?? 0
        case 'conversion_so_far':
            return step.conversionRates?.total ?? 0
        case 'conversion_from_prev':
            return step.conversionRates?.fromPrevious ?? 0
        case 'median_time':
            return step.median_conversion_time ?? 0
        case 'average_time':
            return step.average_conversion_time ?? 0
        default:
            return 0
    }
}

function compareBreakdownsByColumnKey(
    a: FlattenedFunnelStepByBreakdown,
    b: FlattenedFunnelStepByBreakdown,
    columnKey: string
): number {
    if (columnKey === 'breakdown_value') {
        const aVal =
            Array.isArray(a.breakdown_value) && a.breakdown_value.length > 0 ? a.breakdown_value[0] : a.breakdown_value
        const bVal =
            Array.isArray(b.breakdown_value) && b.breakdown_value.length > 0 ? b.breakdown_value[0] : b.breakdown_value
        if (typeof aVal === 'number' && typeof bVal === 'number') {
            return aVal - bVal
        }
        return String(aVal ?? '').localeCompare(String(bVal ?? ''))
    }
    if (columnKey === 'total_conversion') {
        return (a.conversionRates?.total ?? 0) - (b.conversionRates?.total ?? 0)
    }
    const stepMatch = columnKey.match(/^step_(\d+)_(.+)$/)
    if (stepMatch) {
        return (
            getStepMetric(a.steps?.[parseInt(stepMatch[1])], stepMatch[2]) -
            getStepMetric(b.steps?.[parseInt(stepMatch[1])], stepMatch[2])
        )
    }
    return 0
}

function isFunnelsQueryOrLegacyFilter(
    insightData: Partial<InsightModel> | null | undefined,
    querySource: InsightQueryNode | null
): boolean {
    /**
     * TODO: Remove legacy filter check once all tests are migrated to query-based format.
     * There are still multiple tests relying on the legacy format in funnelDataLogic.test.ts.
     */
    if (insightData?.filters?.insight === InsightType.FUNNELS) {
        return true
    }
    return isFunnelsQuery(querySource)
}

export const funnelDataLogic = kea<funnelDataLogicType>([
    path((key) => ['scenes', 'funnels', 'funnelDataLogic', key]),
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps(DEFAULT_FUNNEL_LOGIC_KEY)),

    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            [
                'querySource as vizQuerySource',
                'insightFilter',
                'funnelsFilter',
                'breakdownFilter',
                'goalLines',
                'series as vizSeries',
                'interval',
                'insightData',
                'insightDataError',
                'getTheme',
                'showLegend',
                'legendPosition',
                'showValuesOnSeries',
                'hasDataWarehouseSeries',
                'labelGroupType',
            ],
            groupsModel,
            ['aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
            router,
            ['searchParams'],
        ],
        actions: [
            insightVizDataLogic(props),
            ['updateInsightFilter', 'updateQuerySource'],
            insightDataLogic(props),
            ['cancelChanges'],
            router,
            ['push'],
        ],
    })),

    actions({
        hideSkewWarning: true,
        setHiddenLegendBreakdowns: (hiddenLegendBreakdowns: string[]) => ({ hiddenLegendBreakdowns }),
        toggleLegendBreakdownVisibility: (breakdown: string) => ({ breakdown }),
        setBreakdownSorting: (breakdownSorting: string | undefined) => ({ breakdownSorting }),
        setConversionWindowInterval: (funnelWindowInterval: number) => ({ funnelWindowInterval }),
        setConversionWindowUnit: (funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit) => ({
            funnelWindowIntervalUnit,
        }),
        commitConversionWindow: true,
    }),

    reducers({
        skewWarningHidden: [
            false,
            {
                hideSkewWarning: () => true,
            },
        ],
        conversionWindowInterval: [
            null as number | null,
            {
                setConversionWindowInterval: (_, { funnelWindowInterval }) => funnelWindowInterval,
                cancelChanges: () => null,
            },
        ],
        conversionWindowUnit: [
            null as FunnelConversionWindowTimeUnit | null,
            {
                setConversionWindowUnit: (_, { funnelWindowIntervalUnit }) => funnelWindowIntervalUnit,
                cancelChanges: () => null,
            },
        ],
    }),

    selectors(({ props }) => ({
        querySource: [
            (s) => [s.vizQuerySource],
            (vizQuerySource) => (isFunnelsQuery(vizQuerySource) ? vizQuerySource : null),
        ],

        series: [
            (s) => [s.vizQuerySource, s.vizSeries],
            (vizQuerySource, series) => (isFunnelsQuery(vizQuerySource) ? (series as FunnelsQuery['series']) : null),
        ],

        isStepsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null
                    ? null
                    : funnelsFilter === undefined
                      ? true
                      : funnelsFilter.funnelVizType === FunnelVizType.Steps
            },
        ],
        isTimeToConvertFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert
            },
        ],
        isTrendsFunnel: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): boolean | null => {
                return funnelsFilter === null ? null : funnelsFilter?.funnelVizType === FunnelVizType.Trends
            },
        ],

        isEmptyFunnel: [
            (s) => [s.querySource],
            (q): boolean | null => {
                return isFunnelsQuery(q)
                    ? q.series.filter((n) => n.kind === NodeKind.EventsNode || n.kind === NodeKind.ActionsNode)
                          .length === 0
                    : null
            },
        ],

        aggregationTargetLabel: [
            (s) => [s.querySource, s.aggregationLabel],
            (querySource, aggregationLabel): Noun => {
                if (!querySource) {
                    return { singular: '', plural: '' }
                }

                if (querySource.funnelsFilter?.customAggregationTarget) {
                    return AGGREGATION_LABEL_FOR_CUSTOM_DATA_WAREHOUSE
                }

                return querySource.funnelsFilter?.funnelAggregateByHogQL
                    ? aggregationLabelForHogQL(querySource.funnelsFilter.funnelAggregateByHogQL)
                    : aggregationLabel(querySource.aggregation_group_type_index)
            },
        ],

        results: [
            (s) => [s.insightData, s.vizQuerySource, s.querySource],
            (insightData, vizQuerySource, querySource): FunnelResultType => {
                // Web analytics queries should not be processed as funnels, even though their response
                // structure may look similar. InsightVizDisplay unconditionally mounts funnelDataLogic,
                // so we need explicit guards to prevent web analytics data from being misinterpreted.
                if (isWebStatsTableQuery(vizQuerySource) || isWebOverviewQuery(vizQuerySource)) {
                    return []
                }

                // TODO: after hooking up data manager, check that we have a funnels result here
                // We check both the legacy filter approach (insightData.filters.insight) and the new
                // query-based approach (querySource.kind) because tests still use the legacy approach.
                // This pattern matches the checks in the 'steps' and 'hasFunnelResults' selectors.
                if (
                    insightData?.filters?.insight !== InsightType.FUNNELS &&
                    querySource &&
                    querySource?.kind !== NodeKind.FunnelsQuery
                ) {
                    return []
                }

                if (insightData?.result) {
                    if (isBreakdownFunnelResults(insightData.result) && insightData.result?.[0]?.[0]?.breakdowns) {
                        // in order to stop the UI having to check breakdowns and breakdown
                        // this collapses breakdowns onto the breakdown property
                        return insightData.result.map((series) =>
                            series.map((step) => {
                                const { breakdowns, ...clone } = step
                                clone.breakdown = breakdowns as (string | number)[]
                                return clone
                            })
                        )
                    }
                    return insightData.result
                }
                return []
            },
        ],
        steps: [
            (s) => [
                s.insightData,
                s.vizQuerySource,
                s.querySource,
                s.breakdownFilter,
                s.results,
                s.isTimeToConvertFunnel,
                s.isStepsFunnel,
            ],
            (
                insightData,
                _vizQuerySource,
                querySource,
                breakdownFilter,
                results,
                isTimeToConvertFunnel,
                isStepsFunnel
            ): FunnelStepWithNestedBreakdown[] => {
                if (!isFunnelsQueryOrLegacyFilter(insightData, querySource)) {
                    return []
                }

                // we need to check wether results are an array, since isTimeToConvertFunnel can be false,
                // while still having "time-to-convert" results in insightData
                if (!isTimeToConvertFunnel && Array.isArray(results) && results.length > 0) {
                    // STEPS compare: the runner returns both periods' steps as a flat tagged list.
                    // Reshape into one step per order with current+previous as nested bars. Trends
                    // also tags rows with compare_label but renders via indexedSteps, so gate on STEPS.
                    if (isStepsFunnel && isFunnelStepsCompareResult(results)) {
                        return aggregateFunnelCompareResult(results)
                    }
                    if (isBreakdownFunnelResults(results)) {
                        const breakdownProperty = breakdownFilter?.breakdowns
                            ? breakdownFilter?.breakdowns.map((b) => b.property).join('::')
                            : (breakdownFilter?.breakdown ?? undefined)
                        // Breakdown + compare: pair each breakdown value's current and previous
                        // funnels so the grouped bars share a color (previous desaturated). Must
                        // precede the plain breakdown path, which would otherwise treat each period
                        // as an independent breakdown value (and double-count the step aggregate).
                        if (isStepsFunnel && isFunnelStepsBreakdownCompareResult(results)) {
                            return aggregateBreakdownCompareResult(results, breakdownProperty)
                        }
                        return aggregateBreakdownResult(results, breakdownProperty).sort((a, b) => a.order - b.order)
                    }
                    return results.sort((a, b) => a.order - b.order)
                }

                return []
            },
        ],
        stepNames: [
            (s) => [s.querySource],
            (querySource): FunnelStepWithNestedBreakdown[] => {
                if (!querySource?.series?.length) {
                    return []
                }

                return querySource.series.map((node, index) => ({
                    action_id:
                        node.kind === NodeKind.ActionsNode
                            ? String(node.id)
                            : node.kind === NodeKind.EventsNode
                              ? (node.event ?? '')
                              : '',
                    name:
                        node.custom_name ||
                        (node.kind === NodeKind.ActionsNode
                            ? `Action ${node.id}`
                            : node.kind === NodeKind.EventsNode
                              ? (node.event ?? '')
                              : ''),
                    custom_name: node.custom_name ?? null,
                    order: index,
                    count: 0,
                    type: (node.kind === NodeKind.ActionsNode ? 'actions' : 'events') as EntityType,
                    average_conversion_time: null,
                    median_conversion_time: null,
                    converted_people_url: '',
                    dropped_people_url: null,
                }))
            },
        ],
        // True when STEPS results carry compare-tagged nested bars (current + previous per step).
        // Compare reshapes the data to look like a 2-value breakdown, so the breakdown baseline /
        // visibility machinery must be bypassed for it.
        isComparedFunnel: [
            (s) => [s.steps],
            (steps): boolean =>
                Array.isArray(steps) &&
                steps.some((step) => step.nested_breakdown?.some((series) => series.compare_label != null)),
        ],
        // True when a compared funnel also carries real breakdown values (breakdown × compare), as
        // opposed to a pure compare funnel whose current/previous bars are not breakdown values.
        // Pure compare is then `isComparedFunnel && !isBreakdownCompareFunnel`: the former bypasses the
        // breakdown machinery entirely, the latter keeps it (table, hidden legend) around the grouped bars.
        isBreakdownCompareFunnel: [
            (s) => [s.results, s.isStepsFunnel],
            (results, isStepsFunnel): boolean => !!isStepsFunnel && isFunnelStepsBreakdownCompareResult(results),
        ],
        stepsWithConversionMetrics: [
            (s) => [s.steps, s.funnelsFilter, s.querySource],
            (
                steps: FunnelStepWithNestedBreakdown[],
                funnelsFilter: FunnelsFilter | null,
                querySource: FunnelsQuery | null
            ): FunnelStepWithConversionMetrics[] => {
                const stepReference = funnelsFilter?.funnelStepReference || FunnelStepReference.total
                // Get optional steps from series (1-indexed)
                const optionalSteps = querySource
                    ? querySource.series
                          .map((_, i: number) => i + 1)
                          .filter((_: number, i: number) => querySource.series[i]?.optionalInFunnel)
                    : []
                return stepsWithConversionMetrics(steps, stepReference, optionalSteps)
            },
        ],

        // hack for experiments to remove displaying baseline from the funnel viz
        disableFunnelBreakdownBaseline: [
            () => [(_, props) => props],
            (props: InsightLogicProps): boolean => !!props.cachedInsight?.disable_baseline,
        ],
        flattenedBreakdowns: [
            (s) => [
                s.stepsWithConversionMetrics,
                s.funnelsFilter,
                s.disableFunnelBreakdownBaseline,
                s.breakdownSorting,
                s.isComparedFunnel,
                s.isBreakdownCompareFunnel,
            ],
            (
                steps: FunnelStepWithConversionMetrics[],
                funnelsFilter: FunnelsFilter | null | undefined,
                disableBaseline: boolean,
                breakdownSorting: string | undefined,
                isComparedFunnel: boolean,
                isBreakdownCompareFunnel: boolean
            ): FlattenedFunnelStepByBreakdown[] => {
                // Pure compare's current/previous bars are not breakdown values — one baseline row
                // per period. Breakdown × compare doubles every row into interleaved period pairs.
                const breakdowns =
                    isComparedFunnel && !isBreakdownCompareFunnel
                        ? flattenedStepsByCompare(steps)
                        : isBreakdownCompareFunnel
                          ? flattenedStepsByBreakdownCompare(steps, funnelsFilter?.layout, disableBaseline)
                          : flattenedStepsByBreakdown(steps, funnelsFilter?.layout, disableBaseline, true)
                if (!breakdownSorting) {
                    return breakdowns
                }

                const isDescending = breakdownSorting.startsWith('-')
                const columnKey = isDescending ? breakdownSorting.slice(1) : breakdownSorting
                const sortOrder = isDescending ? -1 : 1

                return [...breakdowns].sort((a, b) => {
                    return sortOrder * compareBreakdownsByColumnKey(a, b, columnKey)
                })
            },
        ],
        hiddenLegendBreakdowns: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): string[] | undefined => funnelsFilter?.hiddenLegendBreakdowns,
        ],
        breakdownSorting: [
            (s) => [s.funnelsFilter],
            (funnelsFilter: FunnelsFilter | null | undefined): string | undefined => funnelsFilter?.breakdownSorting,
        ],
        resultCustomizations: [(s) => [s.funnelsFilter], (funnelsFilter) => funnelsFilter?.resultCustomizations],
        visibleStepsWithConversionMetrics: [
            (s) => [
                s.stepsWithConversionMetrics,
                s.flattenedBreakdowns,
                s.hiddenLegendBreakdowns,
                s.isComparedFunnel,
                s.isBreakdownCompareFunnel,
            ],
            (
                steps: FunnelStepWithConversionMetrics[],
                flattenedBreakdowns: FlattenedFunnelStepByBreakdown[],
                hiddenLegendBreakdowns: string[] | undefined,
                isComparedFunnel: boolean,
                isBreakdownCompareFunnel: boolean
            ): FunnelStepWithConversionMetrics[] => {
                // Pure compare already shaped nested_breakdown into [current, previous]; skip the
                // breakdown baseline-prepend / hidden-legend reordering, which assumes real breakdowns.
                if (isComparedFunnel && !isBreakdownCompareFunnel) {
                    return steps
                }
                // Count values, not rows — compare doubles rows per period, and a single-value
                // breakdown × compare funnel must not flip into multi-series hidden-legend filtering.
                const isOnlySeries = flattenedBreakdowns.filter((b) => b.compare_label !== 'previous').length <= 1
                // Breakdown + compare: apply hidden-legend filtering by real breakdown value, but keep
                // the grouped current/previous pairing and the shared per-value orders that drive the
                // bar colors — don't run the baseline-prepend / order-remap path below.
                if (isBreakdownCompareFunnel) {
                    return steps.map((step) => ({
                        ...step,
                        nested_breakdown: step.nested_breakdown?.filter(
                            (b) =>
                                isOnlySeries || !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
                        ),
                    }))
                }
                const baseLineSteps = flattenedBreakdowns.find((b) => b.isBaseline)

                // Build a breakdown order lookup from flattenedBreakdowns (already sorted
                // by breakdownSorting) so the graph matches the table order.
                const breakdownOrder = new Map<string, number>()
                flattenedBreakdowns.forEach((b, i) => breakdownOrder.set(getVisibilityKey(b.breakdown_value), i))

                return steps.map((step, stepIndex) => {
                    const nested = (
                        baseLineSteps?.steps
                            ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
                            : step?.nested_breakdown
                    )
                        ?.map((b, breakdownIndex) => ({
                            ...b,
                            order: breakdownIndex,
                        }))
                        ?.filter(
                            (b) =>
                                isOnlySeries || !hiddenLegendBreakdowns?.includes(getVisibilityKey(b.breakdown_value))
                        )
                        ?.sort((a, b) => {
                            const aIdx = breakdownOrder.get(getVisibilityKey(a.breakdown_value)) ?? Infinity
                            const bIdx = breakdownOrder.get(getVisibilityKey(b.breakdown_value)) ?? Infinity
                            return aIdx - bIdx
                        })
                    return {
                        ...step,
                        nested_breakdown: nested,
                    }
                })
            },
        ],

        /*
         * Time-to-convert funnels
         */
        timeConversionResults: [
            (s) => [s.results, s.funnelsFilter],
            (results, funnelsFilter): FunnelsTimeConversionBins | null => {
                if (funnelsFilter?.funnelVizType !== FunnelVizType.TimeToConvert) {
                    return null
                }
                // Compare returns a two-element list tagged with compare_label; take the current period.
                if (Array.isArray(results)) {
                    return (
                        (results as unknown as TimeToConvertCompareBins[]).find(
                            (row) => row.compare_label === 'current'
                        ) ?? null
                    )
                }
                return results as FunnelsTimeConversionBins
            },
        ],
        timeConversionResultsPrevious: [
            (s) => [s.results, s.funnelsFilter],
            (results, funnelsFilter): FunnelsTimeConversionBins | null => {
                if (funnelsFilter?.funnelVizType !== FunnelVizType.TimeToConvert || !Array.isArray(results)) {
                    return null
                }
                return (
                    (results as unknown as TimeToConvertCompareBins[]).find(
                        (row) => row.compare_label === 'previous'
                    ) ?? null
                )
            },
        ],
        histogramGraphData: [
            (s) => [s.timeConversionResults],
            (timeConversionResults): HistogramGraphDatum[] | null =>
                timeConversionBinsToHistogramData(timeConversionResults),
        ],
        histogramGraphDataPrevious: [
            (s) => [s.timeConversionResultsPrevious],
            (timeConversionResultsPrevious): HistogramGraphDatum[] | null =>
                timeConversionBinsToHistogramData(timeConversionResultsPrevious),
        ],
        hasFunnelResults: [
            (s) => [s.insightData, s.funnelsFilter, s.steps, s.histogramGraphData, s.querySource, s.stepNames],
            (insightData, funnelsFilter, steps, histogramGraphData, querySource, stepNames) => {
                if (!isFunnelsQueryOrLegacyFilter(insightData, querySource)) {
                    return false
                }

                if (funnelsFilter?.funnelVizType === FunnelVizType.Steps || !funnelsFilter?.funnelVizType) {
                    return !!(steps && steps[0] && steps[0].count > -1)
                } else if (funnelsFilter.funnelVizType === FunnelVizType.TimeToConvert) {
                    return (histogramGraphData?.length ?? 0) > 0
                } else if (funnelsFilter.funnelVizType === FunnelVizType.Trends) {
                    return (steps?.length ?? 0) > 0 && !!steps?.[0]?.labels
                } else if (funnelsFilter.funnelVizType === FunnelVizType.Flow && stepNames.length > 0) {
                    return true
                }

                return false
            },
        ],
        numericBinCount: [
            (s) => [s.funnelsFilter, s.timeConversionResults],
            (funnelsFilter, timeConversionResults): number => {
                if (funnelsFilter?.binCount === BIN_COUNT_AUTO) {
                    return timeConversionResults?.bins?.length ?? 0
                }
                return funnelsFilter?.binCount ?? 0
            },
        ],

        conversionMetrics: [
            (s) => [s.steps, s.funnelsFilter, s.timeConversionResults, s.insightData],
            (steps, funnelsFilter, timeConversionResults, insightData): FunnelTimeConversionMetrics => {
                // steps should be empty in time conversion view. Return metrics precalculated on backend
                if (funnelsFilter?.funnelVizType === FunnelVizType.TimeToConvert) {
                    return {
                        medianTime: timeConversionResults?.median_conversion_time ?? null,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                // Handle metrics for trends
                if (funnelsFilter?.funnelVizType === FunnelVizType.Trends) {
                    return {
                        medianTime: null,
                        stepRate: 0,
                        totalRate: average((steps?.[0] as unknown as TrendResult)?.data ?? []) / 100,
                    }
                }

                // Handle metrics for steps
                // no concept of funnel_from_step and funnel_to_step here
                if (steps.length <= 1) {
                    return {
                        medianTime: null,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                const toStep = getLastFilledStep(steps)
                const fromStep = getReferenceStep(steps, FunnelStepReference.total)

                return {
                    // The median of the total funnel time isn't the sum of per-step medians, so it's
                    // computed breakdown-agnostically on the backend and carried as a top-level field.
                    medianTime: (insightData as Partial<FunnelsQueryResponse>).total_median_conversion_time ?? null,
                    stepRate: fromStep.count === 0 ? 0 : toStep.count / fromStep.count,
                    totalRate: steps[0].count === 0 ? 0 : steps[steps.length - 1].count / steps[0].count,
                }
            },
        ],
        conversionWindow: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): Required<FunnelConversionWindow> => {
                const { funnelWindowInterval, funnelWindowIntervalUnit } = funnelsFilter || {}
                return {
                    funnelWindowInterval: funnelWindowInterval || 14,
                    funnelWindowIntervalUnit: funnelWindowIntervalUnit || FunnelConversionWindowTimeUnit.Day,
                }
            },
        ],
        incompletenessOffsetFromEnd: [
            (s) => [s.steps, s.conversionWindow],
            (steps, conversionWindow) => {
                if (steps?.[0]?.days === undefined) {
                    return 0
                }

                // subtract conversion window from today and look for a matching day
                const startDate = getIncompleteConversionWindowStartDate(conversionWindow)
                const startIndex = steps[0].days.findIndex((day) => dayjs(day) >= startDate)

                if (startIndex !== undefined && startIndex !== -1) {
                    return startIndex - steps[0].days.length
                }
                return 0
            },
        ],

        /*
         * Advanced options: funnelOrderType, funnelStepReference, exclusions
         */
        advancedOptionsUsedCount: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): number => {
                let count = 0
                if (funnelsFilter?.funnelOrderType && funnelsFilter?.funnelOrderType !== StepOrderValue.ORDERED) {
                    count = count + 1
                }
                if (
                    funnelsFilter?.funnelStepReference &&
                    funnelsFilter?.funnelStepReference !== FunnelStepReference.total
                ) {
                    count = count + 1
                }
                if (funnelsFilter?.exclusions?.length) {
                    count = count + 1
                }
                return count
            },
        ],

        isSkewed: [
            (s) => [s.conversionMetrics, s.skewWarningHidden],
            (conversionMetrics, skewWarningHidden): boolean => {
                return !skewWarningHidden && (conversionMetrics.totalRate < 0.1 || conversionMetrics.totalRate > 0.9)
            },
        ],
        indexedSteps: [
            (s) => [s.steps],
            (steps) => {
                if (!Array.isArray(steps)) {
                    return []
                }
                // Pair rows on `breakdown_value` (no `compare_label`) so current/previous of the
                // same series share the same base color. The downstream color resolver prefers
                // `colorIndex` over `seriesIndex` (see `getTrendResultCustomizationColorToken`),
                // and `LineGraph.processDataset` then dims the previous-period series to 50% alpha.
                const colorIndexMap = new Map<string, number>()
                for (const step of steps) {
                    const key = getFunnelDatasetKey(step)
                    if (!colorIndexMap.has(key)) {
                        colorIndexMap.set(key, colorIndexMap.size)
                    }
                }
                return steps.map((step, index) => {
                    // The funnels runner tags compare rows with `compare_label` but doesn't set
                    // `compare: true`. `LineGraph.processDataset` requires both to dim the previous
                    // line — normalize here so the previous-period series renders at 50% alpha.
                    const stepWithCompare = step as typeof step & {
                        compare_label?: 'current' | 'previous'
                        compare?: boolean
                    }
                    return {
                        ...step,
                        seriesIndex: index,
                        colorIndex: colorIndexMap.get(getFunnelDatasetKey(step)) ?? 0,
                        id: index,
                        compare: stepWithCompare.compare_label != null ? true : stepWithCompare.compare,
                    }
                })
            },
        ],
        getFunnelsColorToken: [
            (s) => [s.resultCustomizations, s.getTheme, s.breakdownFilter, s.querySource],
            (resultCustomizations, getTheme, breakdownFilter, querySource) => {
                return (
                    dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics
                ): [DataColorTheme | null, DataColorToken | null] => {
                    // stringified breakdown value
                    const key = getFunnelDatasetKey(dataset)
                    let breakdownValue = JSON.parse(key)['breakdown_value']
                    breakdownValue = Array.isArray(breakdownValue) ? breakdownValue.join('::') : breakdownValue

                    // dashboard color overrides
                    const logic = dashboardLogic.findMounted({ id: props.dashboardId })
                    const dashboardBreakdownColors = logic?.values.temporaryBreakdownColors
                    const colorOverride = dashboardBreakdownColors?.find(
                        (config) =>
                            config.breakdownValue === breakdownValue &&
                            config.breakdownType === (breakdownFilter?.breakdown_type ?? 'event')
                    )

                    if (colorOverride?.colorToken) {
                        // use the dashboard theme, or fallback to the default theme
                        const dashboardTheme = logic?.values.dataColorTheme || getTheme(undefined)
                        return [dashboardTheme, colorOverride.colorToken]
                    }

                    // use the dashboard theme, or fallback to the insight theme, or the default theme
                    const theme = logic?.values.dataColorTheme || getTheme(querySource?.dataColorTheme)
                    if (!theme) {
                        return [null, null]
                    }

                    return [
                        theme,
                        getFunnelResultCustomizationColorToken(
                            resultCustomizations,
                            theme,
                            dataset,
                            props?.cachedInsight?.disable_baseline
                        ),
                    ]
                }
            },
        ],
        getFunnelsColor: [
            (s) => [s.getFunnelsColorToken],
            (getFunnelsColorToken) => {
                return (dataset: FlattenedFunnelStepByBreakdown | FunnelStepWithConversionMetrics) => {
                    const [colorTheme, colorToken] = getFunnelsColorToken(dataset)
                    const color = colorTheme && colorToken ? getColorFromToken(colorTheme, colorToken) : '#000000'
                    // Current/previous compare bars share a color token (no breakdown_value), so the
                    // previous-period bar is dimmed here to distinguish it — same treatment as trends.
                    return (dataset as FunnelStepWithConversionMetrics).compare_label === 'previous'
                        ? dimPreviousPeriodColor(color)
                        : color
                }
            },
        ],
        isStepOptional: [
            (s) => [s.querySource],
            (querySource: FunnelsQuery | null) => {
                return (step: number) => {
                    if (querySource?.kind === NodeKind.FunnelsQuery) {
                        // step is 1-indexed, series is 0-indexed
                        return querySource.series[step - 1]?.optionalInFunnel === true
                    }
                    return false
                }
            },
        ],

        // Validations
        isFunnelWithEnoughSteps: [(s) => [s.series], (series) => isFunnelWithEnoughSteps(series)],
        isFunnelWithIncompleteDataWarehouseStep: [
            (s) => [s.series],
            (series) => isFunnelWithIncompleteDataWarehouseStep(series),
        ],

        // Exclusion filters
        exclusionDefaultStepRange: [
            (s) => [s.querySource],
            (querySource: FunnelsQuery): FunnelExclusionSteps => ({
                funnelFromStep: 0,
                funnelToStep: (querySource.series || []).length > 1 ? querySource.series.length - 1 : 1,
            }),
        ],
        exclusionFilters: [
            (s) => [s.funnelsFilter],
            (funnelsFilter): FilterType => ({
                events: funnelsFilter?.exclusions?.map(({ funnelFromStep, funnelToStep, ...rest }, index) => ({
                    funnel_from_step: funnelFromStep,
                    funnel_to_step: funnelToStep,
                    order: index,
                    ...seriesNodeToFilter(rest),
                })),
            }),
        ],
    })),

    listeners(({ actions, values }) => ({
        setHiddenLegendBreakdowns: ({ hiddenLegendBreakdowns }) => {
            actions.updateInsightFilter({ hiddenLegendBreakdowns })
        },
        toggleLegendBreakdownVisibility: ({ breakdown }) => {
            values.hiddenLegendBreakdowns?.includes(breakdown)
                ? actions.setHiddenLegendBreakdowns(values.hiddenLegendBreakdowns.filter((b) => b !== breakdown))
                : actions.setHiddenLegendBreakdowns([...(values.hiddenLegendBreakdowns || []), breakdown])
        },
        commitConversionWindow: () => {
            const { conversionWindowInterval, conversionWindowUnit, conversionWindow } = values
            const unit = conversionWindowUnit ?? conversionWindow.funnelWindowIntervalUnit
            const rawInterval = conversionWindowInterval ?? conversionWindow.funnelWindowInterval

            if (!rawInterval) {
                actions.setConversionWindowInterval(conversionWindow.funnelWindowInterval)
                return
            }

            const [min, max] = TIME_INTERVAL_BOUNDS[unit]
            const interval = Math.min(Math.max(rawInterval, min), max)

            if (interval !== rawInterval) {
                actions.setConversionWindowInterval(interval)
            }

            if (
                interval !== conversionWindow.funnelWindowInterval ||
                unit !== conversionWindow.funnelWindowIntervalUnit
            ) {
                actions.updateInsightFilter({
                    funnelWindowInterval: interval,
                    funnelWindowIntervalUnit: unit,
                })
            }
        },
        setBreakdownSorting: ({ breakdownSorting }) => {
            actions.updateInsightFilter({ breakdownSorting })
        },
    })),

    afterMount(({ actions, values }) => {
        // Sync URL with saved sorting on mount
        if (values.breakdownSorting && !values.searchParams.order) {
            actions.push(
                window.location.pathname,
                { ...values.searchParams, order: values.breakdownSorting },
                window.location.hash
            )
        }
    }),
])

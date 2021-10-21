import { kea } from 'kea'
import equal from 'fast-deep-equal'
import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { average, sum } from 'lib/utils'
import { funnelsModel } from '~/models/funnelsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelLogicType } from './funnelLogicType'
import {
    FilterType,
    FunnelVizType,
    FunnelStep,
    FunnelsTimeConversionBins,
    PersonType,
    ViewType,
    FunnelStepWithNestedBreakdown,
    FunnelTimeConversionMetrics,
    FlattenedFunnelStep,
    FunnelStepWithConversionMetrics,
    BinCountValue,
    FunnelConversionWindow,
    FunnelConversionWindowTimeUnit,
    FunnelStepRangeEntityFilter,
    InsightLogicProps,
    FlattenedFunnelStepByBreakdown,
    FunnelCorrelation,
    FunnelCorrelationType,
    FunnelStepReference,
    FunnelAPIResponse,
    TrendResult,
} from '~/types'
import { FunnelLayout, BinCountAuto, FEATURE_FLAGS } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import {
    aggregateBreakdownResult,
    formatDisplayPercentage,
    getClampedStepRangeFilter,
    getLastFilledStep,
    getMeanAndStandardDeviation,
    getReferenceStep,
    getVisibilityIndex,
    isBreakdownFunnelResults,
    isStepsEmpty,
    isValidBreakdownParameter,
} from './funnelUtils'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cleanFilters } from 'scenes/insights/utils/cleanFilters'
import { keyForInsightLogicProps } from 'scenes/insights/sharedUtils'

const DEVIATION_SIGNIFICANCE_MULTIPLIER = 1.5
// Chosen via heuristics by eyeballing some values
// Assuming a normal distribution, then 90% of values are within 1.5 standard deviations of the mean
// which gives a ballpark of 1 highlighting every 10 breakdown values

export const funnelLogic = kea<funnelLogicType>({
    props: {} as InsightLogicProps,
    key: keyForInsightLogicProps('insight_funnel'),

    connect: (props: InsightLogicProps) => ({
        values: [insightLogic(props), ['filters', 'insight', 'insightLoading']],
        actions: [insightLogic(props), ['loadResults', 'loadResultsSuccess'], funnelsModel, ['loadFunnels']],
        logic: [eventUsageLogic, dashboardsModel],
    }),

    actions: () => ({
        clearFunnel: true,
        setFilters: (filters: Partial<FilterType>, refresh = false, mergeWithExisting = true) => ({
            filters,
            refresh,
            mergeWithExisting,
        }),
        setEventExclusionFilters: (filters: Partial<FilterType>) => ({ filters }),
        setOneEventExclusionFilter: (eventFilter: FunnelStepRangeEntityFilter, index: number) => ({
            eventFilter,
            index,
        }),
        saveFunnelInsight: (name: string) => ({ name }),
        setConversionWindow: (conversionWindow: FunnelConversionWindow) => ({ conversionWindow }),
        openPersonsModal: (
            step: FunnelStep | FunnelStepWithNestedBreakdown,
            stepNumber: number,
            breakdown_value?: string | number
        ) => ({
            step,
            stepNumber,
            breakdown_value,
        }),
        setStepReference: (stepReference: FunnelStepReference) => ({ stepReference }),
        changeStepRange: (funnel_from_step?: number, funnel_to_step?: number) => ({
            funnel_from_step,
            funnel_to_step,
        }),
        setIsGroupingOutliers: (isGroupingOutliers) => ({ isGroupingOutliers }),
        setBinCount: (binCount: BinCountValue) => ({ binCount }),
        toggleVisibility: (index: string) => ({ index }),
        toggleVisibilityByBreakdown: (breakdownValue?: number | string) => ({ breakdownValue }),
        setHiddenById: (entry: Record<string, boolean | undefined>) => ({ entry }),

        // Correlation related actions
        setCorrelationTypes: (types: FunnelCorrelationType[]) => ({ types }),
        setPropertyCorrelationTypes: (types: FunnelCorrelationType[]) => ({ types }),
        hideSkewWarning: true,
    }),

    loaders: ({ values }) => ({
        people: [
            [] as any[],
            {
                loadPeople: async (steps) => {
                    return (await api.get('api/person/?uuid=' + steps[0].people.join(','))).results
                },
            },
        ],
        correlations: [
            { events: [] } as Record<'events', FunnelCorrelation[]>,
            {
                loadCorrelations: async () => {
                    return (
                        await api.create('api/insight/funnel/correlation', {
                            ...values.apiParams,
                            funnel_correlation_type: 'events',
                        })
                    ).result
                },
            },
        ],
        propertyCorrelations: [
            {
                events: [],
            } as Record<'events', FunnelCorrelation[]>,
            {
                loadPropertyCorrelations: async (propertyNames: string[]) => {
                    return (
                        await api.create('api/insight/funnel/correlation', {
                            ...values.apiParams,
                            funnel_correlation_type: 'properties',
                            // Name is comma separated list of property names
                            funnel_correlation_names: propertyNames.length
                                ? propertyNames.map((name: string) => name.trim())
                                : ['$all'],
                        })
                    ).result
                },
            },
        ],
        eventWithPropertyCorrelations: [
            {} as Record<string, FunnelCorrelation[]>,
            {
                loadEventWithPropertyCorrelations: async (eventName: string) => {
                    const results = (
                        await api.create('api/insight/funnel/correlation', {
                            ...values.apiParams,
                            funnel_correlation_type: 'event_with_properties',
                            funnel_correlation_event_names: [eventName],
                        })
                    ).result?.events

                    return { [eventName]: results }
                },
            },
        ],
    }),

    reducers: ({ props }) => ({
        people: {
            clearFunnel: () => [],
        },
        conversionWindow: [
            {
                funnel_window_interval_unit: FunnelConversionWindowTimeUnit.Day,
                funnel_window_interval: 14,
            } as FunnelConversionWindow,
            {
                setConversionWindow: (
                    state,
                    { conversionWindow: { funnel_window_interval_unit, funnel_window_interval } }
                ) => {
                    return {
                        ...state,
                        ...(funnel_window_interval_unit ? { funnel_window_interval_unit } : {}),
                        ...(funnel_window_interval ? { funnel_window_interval } : {}),
                    }
                },
            },
        ],
        stepReference: [
            FunnelStepReference.total as FunnelStepReference,
            {
                setStepReference: (_, { stepReference }) => stepReference,
            },
        ],
        isGroupingOutliers: [
            true,
            {
                setIsGroupingOutliers: (_, { isGroupingOutliers }) => isGroupingOutliers,
            },
        ],
        error: [
            null as any,
            {
                [insightLogic(props).actionTypes.startQuery]: () => null,
                [insightLogic(props).actionTypes.endQuery]: (_: any, { exception }: any) => exception ?? null,
                [insightLogic(props).actionTypes.abortQuery]: (_: any, { exception }: any) => exception ?? null,
            },
        ],
        correlationTypes: [
            [FunnelCorrelationType.Success, FunnelCorrelationType.Failure] as FunnelCorrelationType[],
            {
                setCorrelationTypes: (_, { types }) => types,
            },
        ],
        propertyCorrelationTypes: [
            [FunnelCorrelationType.Success, FunnelCorrelationType.Failure] as FunnelCorrelationType[],
            {
                setPropertyCorrelationTypes: (_, { types }) => types,
            },
        ],
        skewWarningHidden: [
            false,
            {
                hideSkewWarning: () => true,
            },
        ],
        eventWithPropertyCorrelations: {
            loadEventWithPropertyCorrelationsSuccess: (state, { eventWithPropertyCorrelations }) => {
                return {
                    ...state,
                    ...eventWithPropertyCorrelations,
                }
            },
        },
    }),

    selectors: ({ selectors }) => ({
        isLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
        loadedFilters: [(s) => [s.insight], ({ filters }) => (filters?.insight === ViewType.FUNNELS ? filters : {})],
        results: [
            (s) => [s.insight],
            ({ filters, result }): FunnelAPIResponse => (filters?.insight === ViewType.FUNNELS ? result : []),
        ],
        resultsLoading: [(s) => [s.insightLoading], (insightLoading) => insightLoading],
        stepResults: [
            (s) => [s.results, s.filters],
            (results, filters) =>
                filters.funnel_viz_type !== FunnelVizType.TimeToConvert
                    ? (results as FunnelStep[] | FunnelStep[][])
                    : [],
        ],
        timeConversionResults: [
            (s) => [s.results, s.filters],
            (results, filters): FunnelsTimeConversionBins | null => {
                return filters.funnel_viz_type === FunnelVizType.TimeToConvert
                    ? (results as FunnelsTimeConversionBins)
                    : null
            },
        ],
        peopleSorted: [
            () => [selectors.stepsWithCount, selectors.people],
            (steps, people) => {
                if (!people) {
                    return null
                }
                const score = (person: PersonType): number => {
                    return steps.reduce(
                        (val, step) => (person.uuid && (step.people?.indexOf(person.uuid) ?? -1) > -1 ? val + 1 : val),
                        0
                    )
                }
                return people.sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [() => [selectors.filters], (filters: FilterType) => isStepsEmpty(filters)],
        propertiesForUrl: [() => [selectors.filters], (filters: FilterType) => cleanFilters(filters)],
        isValidFunnel: [
            () => [selectors.filters, selectors.stepsWithCount, selectors.histogramGraphData],
            (filters, stepsWithCount, histogramGraphData) => {
                if (filters.funnel_viz_type === FunnelVizType.Steps || !filters.funnel_viz_type) {
                    return !!(stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1)
                }
                if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return (histogramGraphData?.length ?? 0) > 0
                }
                if (filters.funnel_viz_type === FunnelVizType.Trends) {
                    return (stepsWithCount?.length ?? 0) > 0 && stepsWithCount?.[0]?.labels
                }
                return false
            },
        ],
        filtersDirty: [
            () => [selectors.filters, selectors.loadedFilters],
            (filters, lastFilters): boolean => !equal(cleanFilters(filters), cleanFilters(lastFilters)),
        ],
        barGraphLayout: [() => [selectors.filters], ({ layout }): FunnelLayout => layout || FunnelLayout.vertical],
        clickhouseFeaturesEnabled: [
            () => [preflightLogic.selectors.preflight],
            // Controls auto-calculation of results and ability to break down values
            (preflight): boolean => !!preflight?.is_clickhouse_enabled,
        ],
        histogramGraphData: [
            () => [selectors.timeConversionResults],
            (timeConversionResults: FunnelsTimeConversionBins) => {
                if ((timeConversionResults?.bins?.length ?? 0) < 2) {
                    return []
                }
                const binSize = timeConversionResults.bins[1][0] - timeConversionResults.bins[0][0]
                const totalCount = sum(timeConversionResults.bins.map(([, count]) => count))
                return timeConversionResults.bins.map(([id, count]: [id: number, count: number]) => {
                    const value = Math.max(0, id)
                    const percent = count / totalCount
                    return {
                        id: value,
                        bin0: value,
                        bin1: value + binSize,
                        count,
                        label: percent === 0 ? '' : `${formatDisplayPercentage(percent)}%`,
                    }
                })
            },
        ],
        areFiltersValid: [
            () => [selectors.numberOfSeries],
            (numberOfSeries) => {
                return numberOfSeries > 1
            },
        ],
        numberOfSeries: [
            () => [selectors.filters],
            (filters): number => (filters.events?.length || 0) + (filters.actions?.length || 0),
        ],
        conversionMetrics: [
            () => [selectors.stepsWithCount, selectors.loadedFilters, selectors.timeConversionResults],
            (stepsWithCount, loadedFilters, timeConversionResults): FunnelTimeConversionMetrics => {
                // stepsWithCount should be empty in time conversion view. Return metrics precalculated on backend
                if (loadedFilters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return {
                        averageTime: timeConversionResults?.average_conversion_time ?? 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                // Handle metrics for trends
                if (loadedFilters.funnel_viz_type === FunnelVizType.Trends) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: average((stepsWithCount?.[0] as unknown as TrendResult)?.data ?? []) / 100,
                    }
                }

                // Handle metrics for steps and trends
                if (stepsWithCount.length <= 1) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                const isAllSteps = loadedFilters.funnel_from_step === -1
                const fromStep = isAllSteps
                    ? getReferenceStep(stepsWithCount, FunnelStepReference.total)
                    : stepsWithCount[loadedFilters.funnel_from_step ?? 0]
                const toStep = isAllSteps
                    ? getLastFilledStep(stepsWithCount)
                    : stepsWithCount[loadedFilters.funnel_to_step ?? 0]

                return {
                    averageTime: toStep?.average_conversion_time || 0,
                    stepRate: toStep.count / fromStep.count,
                    totalRate: stepsWithCount[stepsWithCount.length - 1].count / stepsWithCount[0].count,
                }
            },
        ],
        isSkewed: [
            (s) => [s.conversionMetrics, s.skewWarningHidden],
            (conversionMetrics, skewWarningHidden): boolean => {
                return !skewWarningHidden && (conversionMetrics.totalRate < 0.1 || conversionMetrics.totalRate > 0.9)
            },
        ],
        apiParams: [
            (s) => [s.filters],
            (filters) => {
                /* TODO: Related to #4329. We're mixing `from_dashboard` as both which causes hard to manage code:
                    a) a boolean-based hash param to determine if the insight is saved in a dashboard (when viewing insights page)
                    b) dashboard ID passed as a filter in certain kind of insights when viewing in the dashboard page
                */
                const { from_dashboard } = filters
                const cleanedParams = cleanFilters(filters)
                return {
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                }
            },
        ],
        filterSteps: [
            () => [selectors.apiParams],
            (apiParams) =>
                [...(apiParams.events ?? []), ...(apiParams.actions ?? [])].sort((a, b) => a.order - b.order),
        ],
        eventCount: [() => [selectors.apiParams], (apiParams) => apiParams.events?.length || 0],
        actionCount: [() => [selectors.apiParams], (apiParams) => apiParams.actions?.length || 0],
        interval: [() => [selectors.apiParams], (apiParams) => apiParams.interval || ''],
        stepsWithNestedBreakdown: [
            () => [selectors.stepResults, selectors.apiParams],
            (results, params) => {
                if (isBreakdownFunnelResults(results) && isValidBreakdownParameter(params.breakdown)) {
                    return aggregateBreakdownResult(results, params.breakdown ?? undefined).sort(
                        (a, b) => a.order - b.order
                    )
                }
                return []
            },
        ],
        steps: [
            () => [selectors.stepResults, selectors.stepsWithNestedBreakdown, selectors.filters],
            (results, stepsWithNestedBreakdown, filters): FunnelStepWithNestedBreakdown[] => {
                if (!Array.isArray(results)) {
                    return []
                }
                return !!filters.breakdown
                    ? stepsWithNestedBreakdown
                    : ([...results] as FunnelStep[]).sort((a, b) => a.order - b.order)
            },
        ],
        stepsWithCount: [() => [selectors.steps], (steps) => steps.filter((step) => typeof step.count === 'number')],
        stepsWithConversionMetrics: [
            () => [selectors.steps, selectors.stepReference],
            (steps, stepReference): FunnelStepWithConversionMetrics[] => {
                const stepsWithConversionMetrics = steps.map((step, i) => {
                    const previousCount = i > 0 ? steps[i - 1].count : step.count // previous is faked for the first step
                    const droppedOffFromPrevious = Math.max(previousCount - step.count, 0)

                    const nestedBreakdown = step.nested_breakdown?.map((breakdown, breakdownIndex) => {
                        const previousBreakdownCount =
                            (i > 0 && steps[i - 1].nested_breakdown?.[breakdownIndex].count) || 0
                        const firstBreakdownCount = steps[0]?.nested_breakdown?.[breakdownIndex].count || 0
                        const _droppedOffFromPrevious = Math.max(previousBreakdownCount - breakdown.count, 0)
                        const conversionRates = {
                            fromPrevious: previousBreakdownCount === 0 ? 0 : breakdown.count / previousBreakdownCount,
                            total: breakdown.count / firstBreakdownCount,
                        }
                        return {
                            ...breakdown,
                            droppedOffFromPrevious: _droppedOffFromPrevious,
                            conversionRates: {
                                ...conversionRates,
                                fromBasisStep:
                                    stepReference === FunnelStepReference.total
                                        ? conversionRates.total
                                        : conversionRates.fromPrevious,
                            },
                        }
                    })
                    const conversionRates = {
                        fromPrevious: previousCount === 0 ? 0 : step.count / previousCount,
                        total: step.count / steps[0].count,
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
                                fromPrevious: isOutlier(
                                    item.conversionRates.fromPrevious,
                                    meanFromPrevious,
                                    stdDevFromPrevious
                                ),
                                fromBasisStep: isOutlier(
                                    item.conversionRates.fromBasisStep,
                                    meanFromBasis,
                                    stdDevFromBasis
                                ),
                                total: isOutlier(item.conversionRates.total, meanTotal, stdDevTotal),
                            },
                        }
                    })

                    return {
                        ...step,
                        nested_breakdown: nestedBreakdown,
                    }
                })
            },
        ],
        hiddenLegendKeys: [
            () => [selectors.filters],
            (filters) => {
                if (!featureFlagLogic.values.featureFlags[FEATURE_FLAGS.FUNNEL_VERTICAL_BREAKDOWN]) {
                    return {}
                }
                return filters.hiddenLegendKeys ?? {}
            },
        ],
        visibleStepsWithConversionMetrics: [
            () => [
                selectors.stepsWithConversionMetrics,
                selectors.hiddenLegendKeys,
                selectors.flattenedStepsByBreakdown,
            ],
            (steps, hiddenLegendKeys, flattenedStepsByBreakdown) => {
                const baseLineSteps = flattenedStepsByBreakdown.find((b) => b.isBaseline)
                return steps.map((step, stepIndex) => ({
                    ...step,
                    nested_breakdown: (!!baseLineSteps?.steps
                        ? [baseLineSteps.steps[stepIndex], ...(step?.nested_breakdown ?? [])]
                        : step?.nested_breakdown
                    )
                        ?.map((b, breakdownIndex) => ({
                            ...b,
                            order: breakdownIndex,
                        }))
                        ?.filter((b) => {
                            return !hiddenLegendKeys[getVisibilityIndex(step, b.breakdown_value)]
                        }),
                }))
            },
        ],
        flattenedSteps: [
            () => [selectors.stepsWithConversionMetrics],
            (steps): FlattenedFunnelStep[] => {
                const flattenedSteps: FlattenedFunnelStep[] = []
                steps.forEach((step) => {
                    flattenedSteps.push({
                        ...step,
                        rowKey: step.order,
                        nestedRowKeys: step.nested_breakdown
                            ? step.nested_breakdown.map((breakdownStep) =>
                                  getVisibilityIndex(step, breakdownStep.breakdown_value)
                              )
                            : [],
                        isBreakdownParent: !!step.nested_breakdown?.length,
                    })
                    if (step.nested_breakdown?.length) {
                        step.nested_breakdown.forEach((breakdownStep, i) => {
                            flattenedSteps.push({
                                ...breakdownStep,
                                rowKey: getVisibilityIndex(step, breakdownStep.breakdown_value),
                                breakdownIndex: i,
                            })
                        })
                    }
                })
                return flattenedSteps
            },
        ],
        flattenedStepsByBreakdown: [
            () => [selectors.stepsWithConversionMetrics, selectors.barGraphLayout],
            (steps, layout): FlattenedFunnelStepByBreakdown[] => {
                // Initialize with two rows for rendering graph and header
                const flattenedStepsByBreakdown: FlattenedFunnelStepByBreakdown[] = [
                    { rowKey: 'steps-meta' },
                    { rowKey: 'graph' },
                    { rowKey: 'table-header' },
                ]

                if (steps.length > 0) {
                    const baseStep = steps[0]
                    const lastStep = steps[steps.length - 1]
                    const hasBaseline =
                        layout === FunnelLayout.vertical &&
                        (!baseStep.breakdown || (baseStep.nested_breakdown?.length ?? 0) > 1)
                    // Baseline - total step to step metrics, only add if more than 1 breakdown or not breakdown
                    if (hasBaseline) {
                        flattenedStepsByBreakdown.push({
                            rowKey: 'baseline',
                            isBaseline: true,
                            breakdown: (baseStep.breakdown as string) ?? 'baseline',
                            breakdown_value: 'Baseline',
                            breakdownIndex: 0,
                            steps: steps.map((s) =>
                                Object.assign({}, s, { nested_breakdown: undefined, breakdown_value: 'Baseline' })
                            ),
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
                                rowKey: breakdownStep.breakdown_value ?? i + offset,
                                isBaseline: false,
                                breakdown: (breakdownStep.breakdown as string | number) || 'Other',
                                breakdown_value: breakdownStep.breakdown_value || 'Other',
                                breakdownIndex: i + offset,
                                steps: stepsInBreakdown,
                                conversionRates: {
                                    total:
                                        (stepsInBreakdown[stepsInBreakdown.length - 1]?.count ?? 0) /
                                        (stepsInBreakdown[0]?.count ?? 1),
                                },
                                significant: stepsInBreakdown.some((step) =>
                                    step.significant ? Object.values(step.significant).some((val) => val) : false
                                ),
                            })
                        })
                    }
                }
                return flattenedStepsByBreakdown
            },
        ],
        flattenedBreakdowns: [
            () => [selectors.flattenedStepsByBreakdown],
            (breakdowns): FlattenedFunnelStepByBreakdown[] => {
                return breakdowns.filter((b) => b.breakdown)
            },
        ],
        numericBinCount: [
            () => [selectors.filters, selectors.timeConversionResults],
            (filters, timeConversionResults): number => {
                if (filters.bin_count === BinCountAuto) {
                    return timeConversionResults?.bins?.length ?? 0
                }
                return filters.bin_count ?? 0
            },
        ],
        exclusionDefaultStepRange: [
            () => [selectors.numberOfSeries, selectors.areFiltersValid],
            (numberOfSeries, areFiltersValid): Omit<FunnelStepRangeEntityFilter, 'id' | 'name'> => ({
                funnel_from_step: 0,
                funnel_to_step: areFiltersValid ? numberOfSeries - 1 : 1,
            }),
        ],
        exclusionFilters: [
            () => [selectors.filters],
            (filters: FilterType): FilterType => ({
                events: filters.exclusions,
            }),
        ],
        areExclusionFiltersValid: [
            () => [selectors.error],
            (e: any): boolean => {
                return !(e?.status === 400 && e?.type === 'validation_error')
            },
        ],
        correlationValues: [
            () => [selectors.correlations, selectors.correlationTypes],
            (correlations, correlationTypes): FunnelCorrelation[] => {
                return correlations.events
                    ?.filter((correlation) => correlationTypes.includes(correlation.correlation_type))
                    .map((value) => {
                        return {
                            ...value,
                            odds_ratio:
                                value.correlation_type === FunnelCorrelationType.Success
                                    ? value.odds_ratio
                                    : 1 / value.odds_ratio,
                        }
                    })
                    .sort((first, second) => {
                        return second.odds_ratio - first.odds_ratio
                    })
            },
        ],
        propertyCorrelationValues: [
            () => [selectors.propertyCorrelations, selectors.propertyCorrelationTypes],
            (propertyCorrelations, propertyCorrelationTypes): FunnelCorrelation[] => {
                return propertyCorrelations.events
                    ?.filter((correlation) => propertyCorrelationTypes.includes(correlation.correlation_type))
                    .map((value) => {
                        return {
                            ...value,
                            odds_ratio:
                                value.correlation_type === FunnelCorrelationType.Success
                                    ? value.odds_ratio
                                    : 1 / value.odds_ratio,
                        }
                    })
                    .sort((first, second) => {
                        return second.odds_ratio - first.odds_ratio
                    })
            },
        ],
        eventWithPropertyCorrelationsValues: [
            () => [selectors.eventWithPropertyCorrelations, selectors.correlationTypes],
            (eventWithPropertyCorrelations, correlationTypes): Record<string, FunnelCorrelation[]> => {
                const eventWithPropertyCorrelationsValues: Record<string, FunnelCorrelation[]> = {}
                for (const key in eventWithPropertyCorrelations) {
                    if (eventWithPropertyCorrelations.hasOwnProperty(key)) {
                        eventWithPropertyCorrelationsValues[key] = eventWithPropertyCorrelations[key]
                            ?.filter((correlation) => correlationTypes.includes(correlation.correlation_type))
                            .map((value) => {
                                return {
                                    ...value,
                                    odds_ratio:
                                        value.correlation_type === FunnelCorrelationType.Success
                                            ? value.odds_ratio
                                            : 1 / value.odds_ratio,
                                }
                            })
                            .sort((first, second) => {
                                return second.odds_ratio - first.odds_ratio
                            })
                    }
                }
                return eventWithPropertyCorrelationsValues
            },
        ],
        eventHasPropertyCorrelations: [
            () => [selectors.eventWithPropertyCorrelationsValues],
            (eventWithPropertyCorrelationsValues): ((eventName: string) => boolean) => {
                return (eventName) => {
                    return !!eventWithPropertyCorrelationsValues[eventName]
                }
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        loadResultsSuccess: async ({ insight }) => {
            if (insight.filters?.insight !== ViewType.FUNNELS) {
                return
            }
            // hide all but the first five breakdowns for each step
            values.steps?.forEach((step) => {
                values.flattenedStepsByBreakdown
                    ?.filter((s) => !!s.breakdown)
                    ?.slice(5)
                    .forEach((b) => {
                        actions.setHiddenById({ [getVisibilityIndex(step, b.breakdown_value)]: true })
                    })
            })

            // load the old people table
            if (!values.clickhouseFeaturesEnabled) {
                if ((values.stepsWithCount[0]?.people?.length ?? 0) > 0) {
                    actions.loadPeople(values.stepsWithCount)
                }
            }

            // load correlation table after funnel. Maybe parallel?
            if (
                featureFlagLogic.values.featureFlags[FEATURE_FLAGS.CORRELATION_ANALYSIS] &&
                values.clickhouseFeaturesEnabled
            ) {
                actions.loadCorrelations()
                // Hardcoded for initial testing
                actions.loadPropertyCorrelations(['$all'])
            }
        },
        toggleVisibilityByBreakdown: ({ breakdownValue }) => {
            values.visibleStepsWithConversionMetrics?.forEach((step) => {
                const key = getVisibilityIndex(step, breakdownValue)
                const currentIsHidden = !!values.hiddenLegendKeys?.[key]

                actions.setHiddenById({ [key]: currentIsHidden ? undefined : true })
            })
        },
        toggleVisibility: ({ index }) => {
            const currentIsHidden = !!values.hiddenLegendKeys?.[index]

            actions.setFilters({
                hiddenLegendKeys: {
                    ...values.hiddenLegendKeys,
                    [`${index}`]: currentIsHidden ? undefined : true,
                },
            })
        },
        setHiddenById: ({ entry }) => {
            const nextEntries = Object.fromEntries(
                Object.entries(entry).map(([index, hiddenState]) => [index, hiddenState ? true : undefined])
            )

            actions.setFilters({
                hiddenLegendKeys: {
                    ...values.hiddenLegendKeys,
                    ...nextEntries,
                },
            })
        },
        setFilters: ({ filters, mergeWithExisting }) => {
            const cleanedParams = cleanFilters(
                mergeWithExisting ? { ...values.filters, ...filters } : filters,
                values.filters
            )
            insightLogic(props).actions.setFilters(cleanedParams)
        },
        setEventExclusionFilters: ({ filters }) => {
            actions.setFilters({
                ...values.filters,
                exclusions: filters.events as FunnelStepRangeEntityFilter[],
            })
        },
        setOneEventExclusionFilter: ({ eventFilter, index }) => {
            actions.setFilters({
                ...values.filters,
                exclusions: values.filters.exclusions
                    ? values.filters.exclusions.map((e, e_i) =>
                          e_i === index
                              ? getClampedStepRangeFilter({ stepRange: eventFilter, filters: values.filters })
                              : e
                      )
                    : [],
            })
        },
        clearFunnel: ({}) => {
            actions.setFilters({ new_entity: values.filters.new_entity }, false, true)
        },
        saveFunnelInsight: async ({ name }) => {
            await api.create('api/insight', {
                filters: values.filters,
                name,
                saved: true,
            })
            actions.loadFunnels()
        },
        openPersonsModal: ({ step, stepNumber, breakdown_value }) => {
            personsModalLogic.actions.loadPeople({
                action: { id: step.action_id, name: step.name, properties: [], type: step.type },
                breakdown_value: breakdown_value !== undefined ? breakdown_value : undefined,
                label: step.name,
                date_from: '',
                date_to: '',
                filters: values.filters,
                saveOriginal: true,
                funnelStep: stepNumber,
            })
        },
        changeStepRange: ({ funnel_from_step, funnel_to_step }) => {
            actions.setFilters({
                funnel_from_step,
                funnel_to_step,
            })
        },
        setBinCount: async ({ binCount }) => {
            actions.setFilters(binCount && binCount !== BinCountAuto ? { bin_count: binCount } : {})
        },
        setConversionWindow: async () => {
            actions.setFilters(values.conversionWindow)
        },
    }),
})

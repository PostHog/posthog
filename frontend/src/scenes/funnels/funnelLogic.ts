import { isBreakpoint, kea } from 'kea'
import equal from 'fast-deep-equal'
import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { autocorrectInterval, sum, uuid } from 'lib/utils'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { funnelsModel } from '~/models/funnelsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelLogicType } from './funnelLogicType'
import {
    EntityTypes,
    FilterType,
    FunnelVizType,
    FunnelResult,
    FunnelStep,
    FunnelsTimeConversionBins,
    PersonType,
    ViewType,
    FunnelStepWithNestedBreakdown,
    FunnelTimeConversionMetrics,
    LoadedRawFunnelResults,
    FlattenedFunnelStep,
    FunnelStepWithConversionMetrics,
    BinCountValue,
    FunnelConversionWindow,
    FunnelConversionWindowTimeUnit,
    FunnelStepRangeEntityFilter,
    SharedInsightLogicProps,
    FlattenedFunnelStepByBreakdown,
    FunnelAPIResponse,
} from '~/types'
import { FunnelLayout, BinCountAuto, FEATURE_FLAGS } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import {
    aggregateBreakdownResult,
    cleanBinResult,
    deepCleanFunnelExclusionEvents,
    formatDisplayPercentage,
    getClampedStepRangeFilter,
    getLastFilledStep,
    getReferenceStep,
    getVisibilityIndex,
    isBreakdownFunnelResults,
    isStepsEmpty,
    isValidBreakdownParameter,
    pollFunnel,
} from './funnelUtils'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { router } from 'kea-router'
import { getDefaultEventName } from 'lib/utils/getAppContext'
import { dashboardsModel } from '~/models/dashboardsModel'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

export const cleanFunnelParams = (filters: Partial<FilterType>, discardFiltersNotUsedByFunnels = false): FilterType => {
    const breakdownEnabled = filters.funnel_viz_type === FunnelVizType.Steps

    return {
        // Use "discardFiltersNotUsedByFunnels" to get funnel params that you can compare.
        ...(discardFiltersNotUsedByFunnels ? {} : filters),
        ...(filters.date_from ? { date_from: filters.date_from } : {}),
        ...(filters.date_to ? { date_to: filters.date_to } : {}),
        ...(filters.actions ? { actions: filters.actions } : {}),
        ...(filters.events ? { events: filters.events } : {}),
        ...(filters.display ? { display: filters.display } : {}),
        ...(filters.layout ? { layout: filters.layout } : {}),
        ...(filters.interval ? { interval: filters.interval } : {}),
        ...(filters.properties ? { properties: filters.properties } : {}),
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
        ...(filters.funnel_step ? { funnel_step: filters.funnel_step } : {}),
        ...(filters.funnel_viz_type
            ? { funnel_viz_type: filters.funnel_viz_type }
            : { funnel_viz_type: FunnelVizType.Steps }),
        ...(filters.funnel_step ? { funnel_to_step: filters.funnel_step } : {}),
        ...(filters.entrance_period_start ? { entrance_period_start: filters.entrance_period_start } : {}),
        ...(filters.drop_off ? { drop_off: filters.drop_off } : {}),
        ...(filters.funnel_step_breakdown !== undefined
            ? { funnel_step_breakdown: filters.funnel_step_breakdown }
            : {}),
        ...(filters.bin_count && filters.bin_count !== BinCountAuto ? { bin_count: filters.bin_count } : {}),
        ...(filters.funnel_window_interval_unit
            ? { funnel_window_interval_unit: filters.funnel_window_interval_unit }
            : {}),
        ...(filters.funnel_window_interval ? { funnel_window_interval: filters.funnel_window_interval } : {}),
        ...(filters.funnel_order_type ? { funnel_order_type: filters.funnel_order_type } : {}),
        ...(filters.hiddenLegendKeys ? { hiddenLegendKeys: filters.hiddenLegendKeys } : {}),
        exclusions: deepCleanFunnelExclusionEvents(filters),
        interval: autocorrectInterval(filters),
        breakdown: breakdownEnabled ? filters.breakdown || undefined : undefined,
        breakdown_type: breakdownEnabled ? filters.breakdown_type || undefined : undefined,
        insight: ViewType.FUNNELS,
    }
}

export interface FunnelLogicProps extends SharedInsightLogicProps {
    refresh?: boolean
    exclusionFilters?: Partial<FilterType>
}

export const funnelLogic = kea<funnelLogicType<FunnelLogicProps>>({
    props: {} as FunnelLogicProps,
    key: (props) => {
        return props.dashboardItemId || 'insight_funnel'
    },

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
        setCachedResults: (filters: Partial<FilterType>, results: FunnelAPIResponse) => ({ filters, results }),
        toggleVisibility: (index: string) => ({ index }),
        toggleVisibilityByBreakdown: (breakdownValue?: number | string) => ({ breakdownValue }),
        setHiddenById: (entry: Record<string, boolean | undefined>) => ({ entry }),
    }),

    connect: {
        actions: [insightHistoryLogic, ['createInsight'], funnelsModel, ['loadFunnels']],
        logic: [insightLogic, eventUsageLogic, dashboardsModel],
    },

    loaders: ({ props, values }) => ({
        rawResults: [
            { results: [], filters: {} } as LoadedRawFunnelResults,
            {
                setCachedResults: ({ results, filters }) => {
                    return { results, filters }
                },
                loadResults: async (refresh = false, breakpoint): Promise<LoadedRawFunnelResults> => {
                    const { apiParams, eventCount, actionCount, interval, filters } = values

                    if (
                        !refresh &&
                        (props.cachedResults || props.preventLoading) &&
                        equal(cleanFunnelParams(values.filters, true), cleanFunnelParams(props.filters || {}, true))
                    ) {
                        return { results: props.cachedResults, filters }
                    }

                    // Don't bother making any requests if filters aren't valid
                    if (!values.areFiltersValid) {
                        return { results: [], filters }
                    }

                    await breakpoint(250)

                    async function loadFunnelResults(): Promise<FunnelResult> {
                        try {
                            const result = await pollFunnel({
                                ...apiParams,
                                refresh,
                            })
                            breakpoint()
                            eventUsageLogic.actions.reportFunnelCalculated(
                                eventCount,
                                actionCount,
                                interval,
                                filters.funnel_viz_type,
                                true
                            )
                            if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                                return cleanBinResult(result)
                            }
                            return result
                        } catch (e) {
                            breakpoint()
                            eventUsageLogic.actions.reportFunnelCalculated(
                                eventCount,
                                actionCount,
                                interval,
                                filters.funnel_viz_type,
                                false,
                                e.message
                            )
                            throw e
                        }
                    }

                    const queryId = uuid()
                    const dashboardItemId = props.dashboardItemId || props.fromDashboardItemId

                    insightLogic.actions.startQuery(queryId)
                    if (dashboardItemId) {
                        dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, true, null)
                    }

                    let resultsPackage: LoadedRawFunnelResults = { results: [], filters }
                    try {
                        const result = await loadFunnelResults()
                        breakpoint()
                        resultsPackage = { ...resultsPackage, results: result.result }
                        insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, result.last_refresh)
                        if (dashboardItemId) {
                            dashboardsModel.actions.updateDashboardRefreshStatus(
                                dashboardItemId,
                                false,
                                result.last_refresh
                            )
                        }
                        return resultsPackage
                    } catch (e) {
                        if (!isBreakpoint(e)) {
                            insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, null, e)
                            if (dashboardItemId) {
                                dashboardsModel.actions.updateDashboardRefreshStatus(dashboardItemId, false, null)
                            }
                            console.error(e)
                        }
                        return resultsPackage
                    }
                },
            },
        ],
        people: [
            [] as any[],
            {
                loadPeople: async (steps) => {
                    return (await api.get('api/person/?uuid=' + steps[0].people.join(','))).results
                },
            },
        ],
    }),

    reducers: ({ props }) => ({
        filters: [
            (props.filters || {}) as FilterType,
            {
                setFilters: (state, { filters, mergeWithExisting }) => {
                    // make sure exclusion steps are clamped within new step range
                    const newFilters = {
                        ...filters,
                        ...getClampedStepRangeFilter({ filters: { ...state, ...filters } }),
                        exclusions: (filters.exclusions || state.exclusions || []).map((e) =>
                            getClampedStepRangeFilter({ stepRange: e, filters })
                        ),
                    }
                    return mergeWithExisting ? { ...state, ...newFilters } : newFilters
                },
                setEventExclusionFilters: (state, { filters }) => ({
                    ...state,
                    exclusions: filters.events as FunnelStepRangeEntityFilter[],
                }),
                setOneEventExclusionFilter: (state, { eventFilter, index }) => ({
                    ...state,
                    exclusions: state.exclusions
                        ? state.exclusions.map((e, e_i) =>
                              e_i === index ? getClampedStepRangeFilter({ stepRange: eventFilter, filters: state }) : e
                          )
                        : [],
                }),
                clearFunnel: (state) => ({ new_entity: state.new_entity }),
                setCachedResultsSuccess: (_, { rawResults }) => rawResults.filters,
            },
        ],
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
            null as any, // TODO: Error typing in typescript doesn't exist natively
            {
                [insightLogic.actionTypes.startQuery]: () => null,
                [insightLogic.actionTypes.endQuery]: (_, { exception }) => exception ?? null,
                [insightLogic.actionTypes.abortQuery]: (_, { exception }) => exception ?? null,
            },
        ],
    }),

    selectors: ({ props, selectors }) => ({
        isLoading: [(s) => [s.rawResultsLoading], (rawResultsLoading) => rawResultsLoading],
        results: [(s) => [s.rawResults], (rawResults) => rawResults.results],
        resultsLoading: [(s) => [s.rawResultsLoading], (rawResultsLoading) => rawResultsLoading],
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
        lastAppliedFilters: [(s) => [s.rawResults], (rawResults) => rawResults.filters],
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
        propertiesForUrl: [() => [selectors.filters], (filters: FilterType) => cleanFunnelParams(filters)],
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
            () => [selectors.filters, selectors.lastAppliedFilters],
            (filters, lastFilters): boolean =>
                !equal(cleanFunnelParams(filters, true), cleanFunnelParams(lastFilters, true)),
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
            () => [selectors.stepsWithCount, selectors.filters, selectors.timeConversionResults],
            (stepsWithCount, filters, timeConversionResults): FunnelTimeConversionMetrics => {
                // stepsWithCount should be empty in time conversion view. Return metrics precalculated on backend
                if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return {
                        averageTime: timeConversionResults?.average_conversion_time ?? 0,
                        stepRate: 0,
                        totalRate: 0,
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

                const isAllSteps = filters.funnel_from_step === -1
                const fromStep = isAllSteps
                    ? getReferenceStep(stepsWithCount, FunnelStepReference.total)
                    : stepsWithCount[filters.funnel_from_step ?? 0]
                const toStep = isAllSteps
                    ? getLastFilledStep(stepsWithCount)
                    : stepsWithCount[filters.funnel_to_step ?? 0]

                return {
                    averageTime: toStep?.average_conversion_time || 0,
                    stepRate: toStep.count / fromStep.count,
                    totalRate: stepsWithCount[stepsWithCount.length - 1].count / stepsWithCount[0].count,
                }
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
                const cleanedParams = cleanFunnelParams(filters)
                return {
                    ...(props.refresh ? { refresh: true } : {}),
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
                return steps.map((step, i) => {
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
    }),

    listeners: ({ actions, values, props }) => ({
        loadResultsSuccess: async () => {
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
            if (!props.dashboardItemId) {
                if (!insightLogic.values.insight.id) {
                    actions.createInsight(values.filters)
                } else {
                    insightLogic.actions.updateInsightFilters(values.filters)
                }
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
        setFilters: ({ refresh }) => {
            // No calculate button on Clickhouse, but query performance is suboptimal on psql
            const { clickhouseFeaturesEnabled } = values
            // If user started from empty state (<2 steps) and added a new step
            const filterLength = (filters: Partial<FilterType>): number =>
                (filters?.events?.length || 0) + (filters?.actions?.length || 0)
            const shouldRefresh = filterLength(values.filters) === 2 && filterLength(values.lastAppliedFilters) === 1
            // If layout or visibility is the only thing that changes
            const onlyLayoutOrVisibilityChanged = equal(
                Object.assign({}, values.filters, { layout: undefined, hiddenLegendKeys: undefined }),
                Object.assign({}, values.lastAppliedFilters, { layout: undefined, hiddenLegendKeys: undefined })
            )

            if (!onlyLayoutOrVisibilityChanged && (refresh || shouldRefresh || clickhouseFeaturesEnabled)) {
                actions.loadResults()
            }
            const cleanedParams = cleanFunnelParams(values.filters)
            if (!props.dashboardItemId) {
                insightLogic.actions.setAllFilters(cleanedParams)
                insightLogic.actions.setLastRefresh(null)
            }
        },
        setEventExclusionFilters: () => {
            if (!equal(values.filters.exclusions || [], values.lastAppliedFilters.exclusions || [])) {
                actions.loadResults()
            }
        },
        setOneEventExclusionFilter: () => {
            if (!equal(values.filters.exclusions || [], values.lastAppliedFilters.exclusions || [])) {
                actions.loadResults()
            }
        },
        saveFunnelInsight: async ({ name }) => {
            await api.create('api/insight', {
                filters: values.filters,
                name,
                saved: true,
            })
            actions.loadFunnels()
        },
        clearFunnel: async () => {
            if (!props.dashboardItemId) {
                insightLogic.actions.setAllFilters({})
            }
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
    actionToUrl: ({ values, props }) => ({
        setFilters: () => {
            if (!props.dashboardItemId) {
                return ['/insights', values.propertiesForUrl, router.values.hashParams, { replace: true }]
            }
        },
        clearFunnel: () => {
            if (!props.dashboardItemId) {
                return ['/insights', { insight: ViewType.FUNNELS }, router.values.hashParams, { replace: true }]
            }
        },
    }),
    urlToAction: ({ actions, props }) => ({
        '/insights': (_, searchParams: Partial<FilterType>) => {
            if (props.dashboardItemId) {
                return
            }
            if (searchParams.insight === ViewType.FUNNELS) {
                const cleanedParams = cleanFunnelParams(searchParams)
                if (isStepsEmpty(cleanedParams)) {
                    const event = getDefaultEventName()
                    cleanedParams.events = [
                        {
                            id: event,
                            name: event,
                            type: EntityTypes.EVENTS,
                            order: 0,
                        },
                    ]
                }
                actions.setFilters(cleanedParams, true, false)
            }
        },
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            if (values.areFiltersValid) {
                // loadResults gets called in urlToAction for non-dashboard insights
                actions.loadResults()
            }
        },
    }),
})

import { isBreakpoint, kea } from 'kea'
import api from 'lib/api'
import { insightLogic } from 'scenes/insights/insightLogic'
import { autocorrectInterval, objectsEqual, uuid } from 'lib/utils'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { funnelsModel } from '~/models/funnelsModel'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelLogicType } from './funnelLogicType'
import {
    EntityTypes,
    FilterType,
    FunnelVizType,
    FunnelResult,
    FunnelStep,
    FunnelsTimeConversionBins,
    FunnelTimeConversionStep,
    PersonType,
    ViewType,
    FunnelStepWithNestedBreakdown,
    FunnelTimeConversionMetrics,
    FunnelRequestParams,
    LoadedRawFunnelResults,
    BreakdownVisibilityMap,
    FlattenedFunnelStep,
    FunnelStepWithConversionMetrics,
} from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { calcPercentage, cleanBinResult, getLastFilledStep, getReferenceStep } from './funnelUtils'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'
import { router } from 'kea-router'
import { getDefaultEventName } from 'lib/utils/getAppContext'

function aggregateBreakdownResult(
    breakdownList: FunnelStep[][],
    breakdownProperty?: string
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

function isBreakdownFunnelResults(results: FunnelStep[] | FunnelStep[][]): results is FunnelStep[][] {
    return Array.isArray(results) && (results.length === 0 || Array.isArray(results[0]))
}

function isValidBreakdownParameter(
    breakdown: FunnelRequestParams['breakdown']
): breakdown is string | null | undefined {
    return ['string', 'null', 'undefined'].includes(typeof breakdown)
}

function wait(ms = 1000): Promise<any> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

const SECONDS_TO_POLL = 3 * 60

const EMPTY_FUNNEL_RESULTS = {
    results: [],
    timeConversionResults: {
        bins: [],
        average_conversion_time: 0,
    },
}

async function pollFunnel<T = FunnelStep[]>(apiParams: FunnelRequestParams): Promise<FunnelResult<T>> {
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
        interval: autocorrectInterval(filters),
        breakdown: breakdownEnabled ? filters.breakdown || undefined : undefined,
        breakdown_type: breakdownEnabled ? filters.breakdown_type || undefined : undefined,
        insight: ViewType.FUNNELS,
    }
}
const isStepsEmpty = (filters: FilterType): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0

export const funnelLogic = kea<funnelLogicType>({
    key: (props) => {
        return props.dashboardItemId || 'some_funnel'
    },

    actions: () => ({
        clearFunnel: true,
        setFilters: (filters: Partial<FilterType>, refresh = false, mergeWithExisting = true) => ({
            filters,
            refresh,
            mergeWithExisting,
        }),
        saveFunnelInsight: (name: string) => ({ name }),
        loadConversionWindow: (days: number) => ({ days }),
        setConversionWindowInDays: (days: number) => ({ days }),
        openPersonsModal: (
            step: FunnelStep | FunnelStepWithNestedBreakdown,
            stepNumber: number,
            breakdown_value?: string
        ) => ({
            step,
            stepNumber,
            breakdown_value,
        }),
        setStepReference: (stepReference: FunnelStepReference) => ({ stepReference }),
        changeHistogramStep: (from_step: number, to_step: number) => ({ from_step, to_step }),
        setIsGroupingOutliers: (isGroupingOutliers) => ({ isGroupingOutliers }),
        setVisibilityMap: (visibilityMap: BreakdownVisibilityMap) => ({ visibilityMap }),
        setVisibility: (breakdownValue: string, visible: boolean) => ({
            breakdownValue,
            visible,
        }),
    }),

    connect: {
        actions: [insightHistoryLogic, ['createInsight'], funnelsModel, ['loadFunnels']],
        values: [preflightLogic, ['preflight']],
    },

    loaders: ({ props, values }) => ({
        rawResults: [
            EMPTY_FUNNEL_RESULTS as LoadedRawFunnelResults,
            {
                loadResults: async (refresh = false, breakpoint): Promise<LoadedRawFunnelResults> => {
                    if (props.cachedResults && !refresh && values.filters === props.filters) {
                        // TODO: cache timeConversionResults? how does this cachedResults work?
                        return {
                            results: props.cachedResults as FunnelStep[] | FunnelStep[][],
                            timeConversionResults: props.cachedResults as FunnelsTimeConversionBins,
                        }
                    }

                    const { apiParams, eventCount, actionCount, interval, histogramStep, filters } = values

                    async function loadFunnelResults(): Promise<FunnelResult<FunnelStep[] | FunnelStep[][]>> {
                        try {
                            const result = await pollFunnel<FunnelStep[] | FunnelStep[][]>({
                                ...apiParams,
                                ...(refresh ? { refresh } : {}),
                                // Time to convert requires steps funnel api to be called for now. Remove once two api's are functionally separated
                                funnel_viz_type:
                                    filters.funnel_viz_type === FunnelVizType.TimeToConvert
                                        ? FunnelVizType.Steps
                                        : apiParams.funnel_viz_type,
                            })
                            eventUsageLogic.actions.reportFunnelCalculated(eventCount, actionCount, interval, true)
                            return result
                        } catch (e) {
                            breakpoint()
                            eventUsageLogic.actions.reportFunnelCalculated(
                                eventCount,
                                actionCount,
                                interval,
                                false,
                                e.message
                            )
                            throw e
                        }
                    }

                    async function loadBinsResults(): Promise<FunnelsTimeConversionBins> {
                        if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                            // API specs (#5110) require neither funnel_{from|to}_step to be provided if querying
                            // for all steps
                            const isAllSteps = values.histogramStep.from_step === -1

                            const binsResult = await pollFunnel<FunnelsTimeConversionBins>({
                                ...apiParams,
                                ...(refresh ? { refresh } : {}),
                                ...(!isAllSteps ? { funnel_from_step: histogramStep.from_step } : {}),
                                ...(!isAllSteps ? { funnel_to_step: histogramStep.to_step } : {}),
                            })
                            return cleanBinResult(binsResult.result)
                        }
                        return EMPTY_FUNNEL_RESULTS.timeConversionResults
                    }

                    const queryId = uuid()
                    insightLogic.actions.startQuery(queryId)
                    try {
                        const [result, timeConversionResults] = await Promise.all([
                            loadFunnelResults(),
                            loadBinsResults(),
                        ])
                        breakpoint()
                        insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, result.last_refresh)
                        return { results: result.result, timeConversionResults }
                    } catch (e) {
                        if (!isBreakpoint(e)) {
                            insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, null, e)
                            console.error(e)
                        }
                        return EMPTY_FUNNEL_RESULTS
                    }
                },
            },
        ],
        people: [
            [] as any[], // TODO: Type properly
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
                setFilters: (state, { filters, mergeWithExisting }) =>
                    mergeWithExisting ? { ...state, ...filters } : filters,
                clearFunnel: (state) => ({ new_entity: state.new_entity }),
            },
        ],
        people: {
            clearFunnel: () => [],
        },
        conversionWindowInDays: [
            14,
            {
                setConversionWindowInDays: (state, { days }) => {
                    return days >= 1 && days <= 365 ? Math.round(days) : state
                },
            },
        ],
        stepReference: [
            FunnelStepReference.total as FunnelStepReference,
            {
                setStepReference: (_, { stepReference }) => stepReference,
            },
        ],
        histogramStep: [
            { from_step: -1, to_step: -1 } as FunnelTimeConversionStep,
            {
                changeHistogramStep: (_, { from_step, to_step }) => ({ from_step, to_step }),
            },
        ],
        isGroupingOutliers: [
            true,
            {
                setIsGroupingOutliers: (_, { isGroupingOutliers }) => isGroupingOutliers,
            },
        ],
        visibilityMap: [
            {} as BreakdownVisibilityMap, // A map of breakdown values to shown/hidden states, set via checkboxes
            {
                setVisibilityMap: (_, { visibilityMap }) => visibilityMap,
                setVisibility: (state, { breakdownValue, visible }) => {
                    return {
                        ...state,
                        [breakdownValue]: visible,
                    }
                },
            },
        ],
    }),

    selectors: ({ props, selectors }) => ({
        isLoading: [(s) => [s.rawResultsLoading], (rawResultsLoading) => rawResultsLoading],
        results: [(s) => [s.rawResults], (rawResults) => rawResults.results],
        timeConversionBins: [(s) => [s.rawResults], (rawResults) => rawResults.timeConversionResults],
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
            () => [selectors.filters, selectors.results, selectors.stepsWithCount, selectors.timeConversionBins],
            (filters, results, stepsWithCount, timeConversionBins) => {
                if (filters.funnel_viz_type === FunnelVizType.Steps || !filters.funnel_viz_type) {
                    return !!(stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1)
                }
                if (filters.funnel_viz_type === FunnelVizType.TimeToConvert) {
                    return timeConversionBins?.bins?.length > 0
                }
                if (filters.funnel_viz_type === FunnelVizType.Trends) {
                    return results?.length > 0
                }
                return false
            },
        ],
        barGraphLayout: [() => [selectors.filters], ({ layout }): FunnelLayout => layout || FunnelLayout.vertical],
        clickhouseFeaturesEnabled: [
            () => [featureFlagLogic.selectors.featureFlags, selectors.preflight],
            // Controls auto-calculation of results and ability to break down values
            (featureFlags, preflight): boolean =>
                !!(featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] && preflight?.is_clickhouse_enabled),
        ],
        histogramGraphData: [
            () => [selectors.timeConversionBins],
            (timeConversionBins: FunnelsTimeConversionBins) => {
                if (timeConversionBins?.bins.length < 2) {
                    return []
                }
                const binSize = timeConversionBins.bins[1][0] - timeConversionBins.bins[0][0]
                return timeConversionBins.bins.map(([id, count]: [id: number, count: number]) => {
                    const value = Math.max(0, id)
                    return {
                        id: value,
                        bin0: value,
                        bin1: value + binSize,
                        count,
                    }
                })
            },
        ],
        histogramStepsDropdown: [
            () => [selectors.stepsWithCount, selectors.conversionMetrics],
            (stepsWithCount, conversionMetrics) => {
                const stepsDropdown: FunnelTimeConversionStep[] = []

                if (stepsWithCount.length > 1) {
                    stepsDropdown.push({
                        label: 'All steps',
                        from_step: -1,
                        to_step: -1,
                        count: stepsWithCount[stepsWithCount.length - 1].count,
                        average_conversion_time: conversionMetrics.averageTime,
                    })
                }

                stepsWithCount.forEach((_, idx) => {
                    if (stepsWithCount[idx + 1]) {
                        stepsDropdown.push({
                            label: `Steps ${idx + 1} and ${idx + 2}`,
                            from_step: idx,
                            to_step: idx + 1,
                            count: stepsWithCount[idx + 1].count,
                            average_conversion_time: stepsWithCount[idx + 1].average_conversion_time ?? 0,
                        })
                    }
                })
                return stepsDropdown
            },
        ],
        areFiltersValid: [
            () => [selectors.filters],
            (filters) => {
                return (filters.events?.length || 0) + (filters.actions?.length || 0) > 1
            },
        ],
        conversionMetrics: [
            () => [selectors.stepsWithCount, selectors.histogramStep],
            (stepsWithCount, timeStep): FunnelTimeConversionMetrics => {
                if (stepsWithCount.length <= 1) {
                    return {
                        averageTime: 0,
                        stepRate: 0,
                        totalRate: 0,
                    }
                }

                const isAllSteps = timeStep.from_step === -1
                const fromStep = isAllSteps
                    ? getReferenceStep(stepsWithCount, FunnelStepReference.total)
                    : stepsWithCount[timeStep.from_step]
                const toStep = isAllSteps ? getLastFilledStep(stepsWithCount) : stepsWithCount[timeStep.to_step]

                return {
                    averageTime: toStep?.average_conversion_time || 0,
                    stepRate: calcPercentage(toStep.count, fromStep.count),
                    totalRate: calcPercentage(stepsWithCount[stepsWithCount.length - 1].count, stepsWithCount[0].count),
                }
            },
        ],
        apiParams: [
            (s) => [s.filters, s.conversionWindowInDays, featureFlagLogic.selectors.featureFlags],
            (filters, conversionWindowInDays, featureFlags) => {
                const { from_dashboard } = filters
                const cleanedParams = cleanFunnelParams(filters)
                return {
                    ...(props.refresh ? { refresh: true } : {}),
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                    funnel_window_days: conversionWindowInDays,
                    ...(!featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] ? { breakdown: null, breakdown_type: null } : {}),
                }
            },
        ],
        eventCount: [() => [selectors.apiParams], (apiParams) => apiParams.events?.length || 0],
        actionCount: [() => [selectors.apiParams], (apiParams) => apiParams.actions?.length || 0],
        interval: [() => [selectors.apiParams], (apiParams) => apiParams.interval || ''],
        stepsWithNestedBreakdown: [
            () => [selectors.results, selectors.apiParams],
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
            () => [selectors.results, selectors.stepsWithNestedBreakdown, selectors.filters],
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
                    const previousCount = i > 0 ? steps[i - 1].count : 0
                    const droppedOffFromPrevious = Math.max(previousCount - step.count, 0)
                    const nestedBreakdown = step.nested_breakdown?.map((breakdown, breakdownIndex) => {
                        const previousBreakdownCount =
                            (i > 0 && steps[i - 1].nested_breakdown?.[breakdownIndex].count) || 0
                        const firstBreakdownCount = steps[0].nested_breakdown?.[breakdownIndex].count || 0
                        const _droppedOffFromPrevious = Math.max(previousBreakdownCount - breakdown.count, 0)
                        const conversionRates = {
                            fromPrevious:
                                previousBreakdownCount === 0
                                    ? 0
                                    : calcPercentage(breakdown.count, previousBreakdownCount),
                            total: calcPercentage(breakdown.count, firstBreakdownCount),
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
                        fromPrevious: previousCount === 0 ? 0 : calcPercentage(step.count, previousCount),
                        total: calcPercentage(step.count, steps[0].count),
                    }
                    return {
                        ...step,
                        droppedOffFromPrevious,
                        nested_breakdown: nestedBreakdown,
                        conversionRates: {
                            ...conversionRates,
                            fromBasisStep:
                                stepReference === FunnelStepReference.total
                                    ? conversionRates.total
                                    : conversionRates.fromPrevious,
                        },
                    }
                })
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
                        isBreakdownParent: !!step.nested_breakdown?.length,
                    })
                    if (step.nested_breakdown?.length) {
                        step.nested_breakdown.forEach((breakdownStep, i) => {
                            flattenedSteps.push({
                                ...breakdownStep,
                                rowKey: `${step.order}-${i}`,
                                breakdownIndex: i,
                            })
                        })
                    }
                })
                return flattenedSteps
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        loadResultsSuccess: async () => {
            // load the old people table
            if (!values.clickhouseFeaturesEnabled) {
                if ((values.stepsWithCount[0]?.people?.length ?? 0) > 0) {
                    actions.loadPeople(values.stepsWithCount)
                }
            }
            // set visibility of all breakdown values
            const visibilityMap: BreakdownVisibilityMap = {}
            values.steps[0].nested_breakdown?.forEach(({ breakdown }) => {
                if (breakdown) {
                    visibilityMap[breakdown] = true
                }
            })
            actions.setVisibilityMap(visibilityMap)
        },
        setFilters: ({ refresh }) => {
            // FUNNEL_BAR_VIZ removes the calculate button on Clickhouse
            // Query performance is suboptimal on psql
            const { clickhouseFeaturesEnabled } = values
            if (refresh || clickhouseFeaturesEnabled) {
                actions.loadResults()
            }
            const cleanedParams = cleanFunnelParams(values.filters)
            insightLogic.actions.setAllFilters(cleanedParams)
            insightLogic.actions.setLastRefresh(null)
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
            insightLogic.actions.setAllFilters({})
        },
        [dashboardItemsModel.actionTypes.refreshAllDashboardItems]: (filters) => {
            if (props.dashboardItemId) {
                actions.setFilters(filters, true)
            }
        },
        loadConversionWindow: async ({ days }, breakpoint) => {
            await breakpoint(1000)
            actions.setConversionWindowInDays(days)
            actions.loadResults()
        },
        openPersonsModal: ({ step, stepNumber, breakdown_value }) => {
            personsModalLogic.actions.loadPeople({
                action: { id: step.action_id, name: step.name, properties: [], type: step.type },
                breakdown_value: breakdown_value || '',
                label: step.name,
                date_from: '',
                date_to: '',
                filters: values.filters,
                saveOriginal: true,
                funnelStep: stepNumber,
            })
        },
        changeHistogramStep: () => {
            actions.loadResults()
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
    urlToAction: ({ actions, values, props }) => ({
        '/insights': (_, searchParams: Partial<FilterType>) => {
            if (props.dashboardItemId) {
                return
            }
            if (searchParams.insight === ViewType.FUNNELS) {
                const currentParams = cleanFunnelParams(values.filters, true)
                const paramsToCheck = cleanFunnelParams(searchParams, true)

                if (!objectsEqual(currentParams, paramsToCheck)) {
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
            }
        },
    }),
})

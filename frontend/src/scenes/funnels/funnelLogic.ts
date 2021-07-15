import { kea } from 'kea'
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
    FunnelStep,
    ChartDisplayType,
    FunnelResult,
    PathType,
    PersonType,
    MappedFunnelStep,
    ViewType,
} from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS, FunnelLayout } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'
import { calcPercentage } from './funnelUtils'
import { personsModalLogic } from 'scenes/trends/personsModalLogic'

function aggregateBreakdownResult({
    result: breakdownList,
    ...apiResponse
}: FunnelResult<FunnelStep[][]>): FunnelResult<MappedFunnelStep[]> {
    let result: MappedFunnelStep[] = []
    if (breakdownList.length) {
        result = breakdownList[0].map((step, i) => ({
            ...step,
            breakdown_value: step.breakdown,
            count: breakdownList.reduce((total, breakdownSteps) => total + breakdownSteps[i].count, 0),
            breakdown: breakdownList.reduce((allEntries, breakdownSteps) => [...allEntries, breakdownSteps[i]], []),
            average_conversion_time: null, // TODO API needs to return a weighted average
            people: [], // We could concatenate and de-dupe the UUIDs from breakdown values here, but it would be more performant to do it on backend
        }))
    }
    return {
        ...apiResponse,
        result,
    }
}

function wait(ms = 1000): Promise<any> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}

const SECONDS_TO_POLL = 3 * 60
interface FunnelRequestParams extends FilterType {
    refresh?: boolean
    from_dashboard?: boolean
    funnel_window_days?: number
}
interface TimeStepOption {
    label: string
    value: number
    average_conversion_time: number
    count: number
}

async function pollFunnel(
    params: FunnelRequestParams
): Promise<FunnelResult & FunnelResult<FunnelStep[][]> & FunnelResult<number[]>> {
    // Tricky: This API endpoint has wildly different return types depending on parameters.
    const { refresh, ...bodyParams } = params
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

export const cleanFunnelParams = (filters: Partial<FilterType>): FilterType => {
    return {
        ...filters,
        ...(filters.date_from ? { date_from: filters.date_from } : {}),
        ...(filters.date_to ? { date_to: filters.date_to } : {}),
        ...(filters.actions ? { actions: filters.actions } : {}),
        ...(filters.events ? { events: filters.events } : {}),
        ...(filters.display ? { display: filters.display } : {}),
        ...(filters.interval ? { interval: filters.interval } : {}),
        ...(filters.properties ? { properties: filters.properties } : {}),
        ...(filters.filter_test_accounts ? { filter_test_accounts: filters.filter_test_accounts } : {}),
        ...(filters.funnel_step ? { funnel_step: filters.funnel_step } : {}),
        ...(filters.funnel_viz_type ? { funnel_viz_type: filters.funnel_viz_type } : {}),
        ...(filters.funnel_step ? { funnel_to_step: filters.funnel_step } : {}),
        interval: autocorrectInterval(filters),
        breakdown: filters.breakdown || undefined,
        breakdown_type: filters.breakdown_type || undefined,

        insight: ViewType.FUNNELS,
    }
}
const isStepsEmpty = (filters: FilterType): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0
export const funnelLogic = kea<funnelLogicType<TimeStepOption>>({
    key: (props) => {
        return props.dashboardItemId || 'some_funnel'
    },

    actions: () => ({
        setSteps: (steps: MappedFunnelStep[]) => ({ steps }),
        clearFunnel: true,
        setFilters: (filters: Partial<FilterType>, refresh = false, mergeWithExisting = true) => ({
            filters,
            refresh,
            mergeWithExisting,
        }),
        saveFunnelInsight: (name: string) => ({ name }),
        setStepsWithCountLoading: (stepsWithCountLoading: boolean) => ({ stepsWithCountLoading }),
        loadConversionWindow: (days: number) => ({ days }),
        setConversionWindowInDays: (days: number) => ({ days }),
        openPersonsModal: (step: FunnelStep | MappedFunnelStep, stepNumber: number, breakdown_value?: string) => ({
            step,
            stepNumber,
            breakdown_value,
        }),
        setStepReference: (stepReference: FunnelStepReference) => ({ stepReference }),
        setBarGraphLayout: (barGraphLayout: FunnelLayout) => ({ barGraphLayout }),
        setTimeConversionBins: (timeConversionBins: number[]) => ({ timeConversionBins }),
        changeHistogramStep: (histogramStep: number) => ({ histogramStep }),
        setIsGroupingOutliers: (isGroupingOutliers) => ({ isGroupingOutliers }),
    }),

    connect: {
        actions: [insightHistoryLogic, ['createInsight'], funnelsModel, ['loadFunnels']],
        values: [featureFlagLogic, ['featureFlags'], preflightLogic, ['preflight']],
    },

    loaders: ({ props, values, actions }) => ({
        results: [
            [] as MappedFunnelStep[],
            {
                loadResults: async (refresh = false, breakpoint): Promise<MappedFunnelStep[]> => {
                    actions.setStepsWithCountLoading(true)
                    if (props.cachedResults && !refresh && values.filters === props.filters) {
                        return props.cachedResults as MappedFunnelStep[]
                    }

                    const { from_dashboard } = values.filters
                    const cleanedParams = cleanFunnelParams(values.filters)
                    const params = {
                        ...(refresh ? { refresh: true } : {}),
                        ...(from_dashboard ? { from_dashboard } : {}),
                        ...cleanedParams,
                        funnel_window_days: values.conversionWindowInDays,
                        ...(!values.featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ]
                            ? { breakdown: null, breakdown_type: null }
                            : {}),
                    }
                    let result // Tricky: pollFunnel would ideally return a FunnelResult or FunnelResult<FunnelStep[][]> based on whether its input params include breakdown
                    const queryId = uuid()
                    insightLogic.actions.startQuery(queryId)
                    const eventCount = params.events?.length || 0
                    const actionCount = params.actions?.length || 0
                    const interval = params.interval || ''

                    try {
                        result = await pollFunnel(params)
                    } catch (e) {
                        breakpoint()
                        insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, null, e)
                        eventUsageLogic.actions.reportFunnelCalculated(
                            eventCount,
                            actionCount,
                            interval,
                            false,
                            e.message
                        )
                        return []
                    }
                    breakpoint()
                    insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, result.last_refresh)
                    if (params.breakdown && values.clickhouseFeatures) {
                        const aggregatedResult = aggregateBreakdownResult(result)
                        actions.setSteps(aggregatedResult.result)
                        return aggregatedResult.result
                    }

                    actions.setSteps(result.result as MappedFunnelStep[])
                    // We make another api call to api/funnels for time conversion data
                    let binsResult: FunnelResult<number[]>
                    if (params.display === ChartDisplayType.FunnelsTimeToConvert && values.stepsWithCount.length > 1) {
                        try {
                            params.funnel_viz_type = 'time_to_convert'
                            params.funnel_to_step = values.histogramStep
                            binsResult = await pollFunnel(params)
                        } catch (e) {
                            breakpoint()
                            insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, null, e)
                            eventUsageLogic.actions.reportFunnelCalculated(
                                eventCount,
                                actionCount,
                                interval,
                                false,
                                e.message
                            )
                            return []
                        }
                        insightLogic.actions.endQuery(queryId, ViewType.FUNNELS, binsResult.last_refresh)
                        actions.setTimeConversionBins(binsResult.result)
                    }
                    return result.result as MappedFunnelStep[]
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
                setFilters: (state, { filters, mergeWithExisting }) =>
                    mergeWithExisting ? { ...state, ...filters } : filters,
                clearFunnel: (state) => ({ new_entity: state.new_entity }),
            },
        ],
        stepsWithCount: [
            [] as MappedFunnelStep[],
            {
                clearFunnel: () => [],
                setSteps: (_, { steps }) => steps,
                setFilters: () => [],
            },
        ],
        stepsWithCountLoading: [
            false,
            {
                setStepsWithCountLoading: (_, { stepsWithCountLoading }) => stepsWithCountLoading,
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
        barGraphLayout: [
            FunnelLayout.vertical as FunnelLayout,
            {
                setBarGraphLayout: (_, { barGraphLayout }) => barGraphLayout,
            },
        ],
        timeConversionBins: [
            [],
            {
                setTimeConversionBins: (_, { timeConversionBins }) => timeConversionBins,
            },
        ],
        histogramStep: [
            1,
            {
                changeHistogramStep: (_, { histogramStep }) => histogramStep,
            },
        ],
        isGroupingOutliers: [
            true,
            {
                setIsGroupingOutliers: (_, { isGroupingOutliers }) => isGroupingOutliers,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        peopleSorted: [
            () => [selectors.stepsWithCount, selectors.people],
            (steps, people) => {
                if (!people) {
                    return null
                }
                const score = (person: PersonType): number => {
                    return steps.reduce(
                        (val, step) => (person.uuid && step.people?.indexOf(person.uuid) > -1 ? val + 1 : val),
                        0
                    )
                }
                return people.sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [() => [selectors.filters], (filters: FilterType) => isStepsEmpty(filters)],
        propertiesForUrl: [() => [selectors.filters], (filters: FilterType) => cleanFunnelParams(filters)],
        isValidFunnel: [
            () => [selectors.stepsWithCount, selectors.timeConversionBins],
            (stepsWithCount: FunnelStep[], timeConversionBins: number[]) => {
                return (
                    (stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1) ||
                    timeConversionBins?.length > 0
                )
            },
        ],
        clickhouseFeatures: [
            () => [selectors.featureFlags, selectors.preflight],
            (featureFlags, preflight) => {
                // Controls auto-calculation of results and ability to break down values
                return !!(featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] && preflight?.is_clickhouse_enabled)
            },
        ],
        funnelPersonsEnabled: [
            () => [selectors.featureFlags, selectors.preflight],
            (featureFlags, preflight) =>
                featureFlags[FEATURE_FLAGS.FUNNEL_PERSONS_MODAL] && preflight?.is_clickhouse_enabled,
        ],
        histogramGraphData: [
            () => [selectors.timeConversionBins],
            (timeConversionBins) => {
                if (timeConversionBins.length < 2) {
                    return []
                }
                const binSize = timeConversionBins[1][0] - timeConversionBins[0][0]
                return timeConversionBins.map(([id, count]: [id: number, count: number]) => {
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
            () => [selectors.stepsWithCount],
            (stepsWithCount) => {
                const stepsDropdown: TimeStepOption[] = []
                stepsWithCount.forEach((_, idx) => {
                    if (stepsWithCount[idx + 1]) {
                        stepsDropdown.push({
                            label: `Steps ${idx + 1} and ${idx + 2}`,
                            value: idx + 1,
                            count: stepsWithCount[idx + 1].count,
                            average_conversion_time: stepsWithCount[idx + 1].average_conversion_time ?? 0,
                        })
                    }
                })
                return stepsDropdown
            },
        ],
        totalConversionRate: [
            () => [selectors.stepsWithCount],
            (stepsWithCount) =>
                stepsWithCount.length > 1
                    ? calcPercentage(stepsWithCount[stepsWithCount.length - 1].count, stepsWithCount[0].count)
                    : 0,
        ],
        areFiltersValid: [
            () => [selectors.filters],
            (filters) => {
                return (filters.events?.length || 0) + (filters.actions?.length || 0) > 1
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        setSteps: async () => {
            if (values.stepsWithCount[0]?.people?.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
            actions.setStepsWithCountLoading(false)
        },
        setFilters: ({ refresh }) => {
            // FUNNEL_BAR_VIZ removes the Calculate button
            // Query performance is suboptimal on psql
            const { clickhouseFeatures } = values
            if (refresh || clickhouseFeatures) {
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
            personsModalLogic.actions.setShowingPeople(true)
            personsModalLogic.actions.loadPeople({
                action: { id: step.action_id, name: step.name, properties: [], type: step.type },
                breakdown_value: breakdown_value || '',
                label: `Persons who completed Step #${stepNumber} - "${step.name}"`,
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
        setSteps: () => {
            if (!props.dashboardItemId) {
                return ['/insights', values.propertiesForUrl, undefined, { replace: true }]
            }
        },
        clearFunnel: () => {
            if (!props.dashboardItemId) {
                return ['/insights', { insight: ViewType.FUNNELS }, undefined, { replace: true }]
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/insights': (_, searchParams: Partial<FilterType>) => {
            if (props.dashboardItemId) {
                return
            }
            if (searchParams.insight === ViewType.FUNNELS) {
                const paramsToCheck = {
                    date_from: searchParams.date_from,
                    date_to: searchParams.date_to,
                    actions: searchParams.actions,
                    events: searchParams.events,
                    display: searchParams.display,
                    interval: searchParams.interval,
                    properties: searchParams.properties,
                }
                const _filters = {
                    date_from: values.filters.date_from,
                    date_to: values.filters.date_to,
                    actions: values.filters.actions,
                    events: values.filters.events,
                    interval: values.filters.interval,

                    properties: values.filters.properties,
                }
                if (!objectsEqual(_filters, paramsToCheck)) {
                    const cleanedParams = cleanFunnelParams(searchParams)
                    if (isStepsEmpty(cleanedParams)) {
                        const event = eventDefinitionsModel.values.eventNames.includes(PathType.PageView)
                            ? PathType.PageView
                            : eventDefinitionsModel.values.eventNames[0]
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

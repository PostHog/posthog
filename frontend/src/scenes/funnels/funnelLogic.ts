import { kea } from 'kea'
import api from 'lib/api'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { autocorrectInterval, objectsEqual, uuid } from 'lib/utils'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { funnelsModel } from '~/models/funnelsModel'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelLogicType } from './funnelLogicType'
import { ChartDisplayType, EntityTypes, FilterType, FunnelResult, FunnelStep, PathType, PersonType } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS, FunnelBarLayout } from 'lib/constants'
import { preflightLogic } from 'scenes/PreflightCheck/logic'
import { trendsLogic } from 'scenes/trends/trendsLogic'
import { FunnelStepReference } from 'scenes/insights/InsightTabs/FunnelTab/FunnelStepReferencePicker'
import { eventDefinitionsModel } from '~/models/eventDefinitionsModel'

function wait(ms = 1000): Promise<any> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}
const SECONDS_TO_POLL = 3 * 60

async function pollFunnel(params: Record<string, any>): Promise<FunnelResult> {
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

export const cleanFunnelParams = (filters: FilterType): FilterType => {
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
        setSteps: (steps: FunnelStep[]) => ({ steps }),
        clearFunnel: true,
        setFilters: (filters: FilterType, refresh = false, mergeWithExisting = true) => ({
            filters,
            refresh,
            mergeWithExisting,
        }),
        saveFunnelInsight: (name: string) => ({ name }),
        setStepsWithCountLoading: (stepsWithCountLoading: boolean) => ({ stepsWithCountLoading }),
        loadConversionWindow: (days: number) => ({ days }),
        setConversionWindowInDays: (days: number) => ({ days }),
        openPersonsModal: (step: FunnelStep, stepNumber: number) => ({ step, stepNumber }),
        setStepReference: (stepReference: FunnelStepReference) => ({ stepReference }),
        setBarGraphLayout: (barGraphLayout: FunnelBarLayout) => ({ barGraphLayout }),
        setTimeConversionBins: (timeConversionBins: number[]) => ({ timeConversionBins }),
    }),

    connect: {
        actions: [insightHistoryLogic, ['createInsight'], funnelsModel, ['loadFunnels']],
        values: [featureFlagLogic, ['featureFlags'], preflightLogic, ['preflight']],
    },

    loaders: ({ props, values, actions }) => ({
        results: [
            [] as FunnelStep[] | number[],
            {
                loadResults: async (refresh = false, breakpoint): Promise<FunnelStep[] | number[]> => {
                    actions.setStepsWithCountLoading(true)
                    if (props.cachedResults && !refresh && values.filters === props.filters) {
                        return props.cachedResults as FunnelStep[] | number[]
                    }

                    const { from_dashboard } = values.filters
                    const cleanedParams = cleanFunnelParams(values.filters)
                    const params = {
                        ...(refresh ? { refresh: true } : {}),
                        ...(from_dashboard ? { from_dashboard } : {}),
                        ...cleanedParams,
                        funnel_window_days: values.conversionWindowInDays,
                    }
                    let result: FunnelResult

                    const queryId = uuid()
                    insightLogic.actions.startQuery(queryId)

                    const eventCount = params.events?.length || 0
                    const actionCount = params.actions?.length || 0
                    const interval = params.interval || ''
                    try {
                        result = await pollFunnel(params)
                        eventUsageLogic.actions.reportFunnelCalculated(eventCount, actionCount, interval, true)
                    } catch (e) {
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
                    if (params.display === ChartDisplayType.FunnelsHistogram) {
                        actions.setTimeConversionBins(result.result as number[])
                    } else {
                        actions.setSteps(result.result as FunnelStep[])
                    }
                    return result.result
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
            [] as FunnelStep[],
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
            FunnelBarLayout.vertical as FunnelBarLayout,
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
        isStepsEmpty: [
            () => [selectors.filters],
            (filters: FilterType) => {
                return isStepsEmpty(filters)
            },
        ],
        propertiesForUrl: [() => [selectors.filters], (filters: FilterType) => cleanFunnelParams(filters)],
        isValidFunnel: [
            () => [selectors.stepsWithCount, selectors.timeConversionBins],
            (stepsWithCount: FunnelStep[], timeConversionBins: number[]) => {
                return (
                    (stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1) ||
                    timeConversionBins.length > 0
                )
            },
        ],
        autoCalculate: [
            () => [selectors.featureFlags, selectors.preflight],
            (featureFlags, preflight) => {
                return !!(featureFlags[FEATURE_FLAGS.FUNNEL_BAR_VIZ] && preflight?.is_clickhouse_enabled)
            },
        ],
        funnelPersonsEnabled: [
            () => [selectors.featureFlags, selectors.preflight],
            (featureFlags, preflight) =>
                featureFlags[FEATURE_FLAGS.FUNNEL_PERSONS_MODAL] && preflight?.is_clickhouse_enabled,
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
            const { autoCalculate } = values
            if (refresh || autoCalculate) {
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
        openPersonsModal: ({ step, stepNumber }) => {
            trendsLogic().actions.setShowingPeople(true)
            trendsLogic().actions.loadPeople(
                { id: step.action_id, name: step.name, properties: [], type: step.type },
                `Persons who completed Step #${stepNumber} - "${step.name}"`,
                '',
                '',
                '',
                true,
                '',
                stepNumber
            )
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
        '/insights': (_, searchParams) => {
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

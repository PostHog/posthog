import { kea } from 'kea'
import api from 'lib/api'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { autocorrectInterval, objectsEqual, uuid } from 'lib/utils'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { funnelsModel } from '~/models/funnelsModel'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { funnelLogicType } from './funnelLogicType'
import { FilterType, FunnelResult, FunnelStep, PersonType } from '~/types'

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

const cleanFunnelParams = (filters: FilterType): FilterType => {
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
        setFilters: (filters: FilterType, refresh: boolean = false) => ({ filters, refresh }),
        saveFunnelInsight: (name: string) => ({ name }),
        setStepsWithCountLoading: (stepsWithCountLoading: boolean) => ({ stepsWithCountLoading }),
        loadConversionWindow: (days: number) => ({ days }),
        setConversionWindowInDays: (days: number) => ({ days }),
    }),

    connect: {
        actions: [insightHistoryLogic, ['createInsight'], funnelsModel, ['loadFunnels']],
    },

    loaders: ({ props, values, actions }) => ({
        results: [
            [] as FunnelStep[],
            {
                loadResults: async (refresh = false, breakpoint): Promise<FunnelStep[]> => {
                    actions.setStepsWithCountLoading(true)
                    if (props.cachedResults && !refresh && values.filters === props.filters) {
                        return props.cachedResults as FunnelStep[]
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
                    actions.setSteps(result.result)
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
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
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
        propertiesForUrl: [
            () => [selectors.filters],
            (filters: FilterType) => {
                const result = {
                    insight: ViewType.FUNNELS,
                    ...cleanFunnelParams(filters),
                }
                return result
            },
        ],
        isValidFunnel: [
            () => [selectors.stepsWithCount],
            (stepsWithCount: FunnelStep[]) => {
                return stepsWithCount && stepsWithCount[0] && stepsWithCount[0].count > -1
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
            if (refresh) {
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
    }),
    actionToUrl: ({ values, props }) => ({
        setSteps: () => {
            if (!props.dashboardItemId) {
                return ['/insights', values.propertiesForUrl]
            }
        },
        clearFunnel: () => {
            if (!props.dashboardItemId) {
                return ['/insights', { insight: ViewType.FUNNELS }]
            }
        },
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/insights': (_: unknown, searchParams: Record<string, any>) => {
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
                    actions.setFilters(cleanFunnelParams(searchParams), !isStepsEmpty(paramsToCheck))
                }
            }
        },
    }),
})

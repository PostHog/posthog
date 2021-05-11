import { kea } from 'kea'
import api from 'lib/api'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { autocorrectInterval, objectsEqual, toParams } from 'lib/utils'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'
import { funnelsModel } from '../../models/funnelsModel'
import { dashboardItemsModel } from '~/models/dashboardItemsModel'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { funnelLogicType } from './funnelLogicType'
import { FilterType, PersonType } from '~/types'
interface FunnelResult {
    is_cached: boolean
    last_refresh: string
    result: []
    type: string
}

interface FunnelParams {
    refresh?: boolean
    from_dashboard?: boolean
}

interface FunnelStep {
    action_id: number
    average_time: number
    count: number
    name: string
    order: number
    people: string[]
    type: string
}

function wait(ms = 1000): Promise<void> {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}
const SECONDS_TO_POLL = 3 * 60

async function pollFunnel(params = {} as FunnelParams & Partial<FilterType>): Promise<FunnelResult> {
    let result = await api.get('api/insight/funnel/?' + toParams(params))
    const start = window.performance.now()
    while (result.result.loading && (window.performance.now() - start) / 1000 < SECONDS_TO_POLL) {
        await wait()
        const { refresh, ...restParams } = params
        result = await api.get('api/insight/funnel/?' + toParams(restParams))
    }
    // if endpoint is still loading after 3 minutes just return default
    if (result.loading) {
        throw { status: 0, statusText: 'Funnel timeout' }
    }
    return result
}

const cleanFunnelParams = (filters: Partial<FilterType>): Partial<FilterType> => {
    const params = {
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
    return params
}

const isStepsEmpty = (filters: Partial<FilterType>): boolean =>
    [...(filters.actions || []), ...(filters.events || [])].length === 0

export const funnelLogic = kea<funnelLogicType>({
    key: (props) => {
        return props.dashboardItemId || 'some_funnel'
    },

    actions: () => ({
        setSteps: (steps: FunnelStep[]) => ({ steps }),
        clearFunnel: true,
        setFilters: (filters, refresh = false) => ({ filters, refresh }),
        saveFunnelInsight: (name) => ({ name }),
        setStepsWithCountLoading: (stepsWithCountLoading) => ({ stepsWithCountLoading }),
    }),

    connect: {
        actions: [insightHistoryLogic, ['createInsight'], funnelsModel, ['loadFunnels']],
    },

    loaders: ({ props, values, actions }) => ({
        results: {
            loadResults: async (refresh = false, breakpoint) => {
                actions.setStepsWithCountLoading(true)
                if (props.cachedResults && !refresh && values.filters === props.filters) {
                    return props.cachedResults
                }

                const { from_dashboard } = values.filters
                const cleanedParams = cleanFunnelParams(values.filters)
                const params = {
                    ...(refresh ? { refresh: true } : {}),
                    ...(from_dashboard ? { from_dashboard } : {}),
                    ...cleanedParams,
                }

                let result

                insightLogic.actions.startQuery()

                const eventCount = params.events?.length
                const actionCount = params.actions?.length
                const interval = params.interval

                try {
                    result = await pollFunnel(params)
                    eventUsageLogic.actions.reportFunnelCalculated(eventCount, actionCount, interval, true)
                } catch (e) {
                    insightLogic.actions.endQuery(ViewType.FUNNELS, null, e)
                    eventUsageLogic.actions.reportFunnelCalculated(eventCount, actionCount, interval, false, e.message)
                    return []
                }
                breakpoint()
                insightLogic.actions.endQuery(ViewType.FUNNELS, result.last_refresh)
                actions.setSteps(result.result)
                return result.result
            },
        },
        people: {
            loadPeople: async (steps) => {
                return (await api.get('api/person/?uuid=' + steps[0].people.join(','))).results
            },
        },
    }),

    reducers: ({ props }) => ({
        filters: [
            (props.filters as Partial<FilterType>) || {},
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                clearFunnel: (state) => ({ new_entity: state.new_entity }),
            },
        ],
        stepsWithCount: [
            [],
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
            clearFunnel: () => null,
        },
    }),

    selectors: ({ selectors }) => ({
        peopleSorted: [
            () => [selectors.stepsWithCount, selectors.people],
            (steps: FunnelStep[], people: PersonType[]) => {
                if (!people) {
                    return null
                }
                const score = (person: PersonType): number => {
                    return steps.reduce((val, step) => (step.people?.indexOf(person.uuid) > -1 ? val + 1 : val), 0)
                }
                return people.sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [
            () => [selectors.filters],
            (filters: Partial<FilterType>) => {
                return isStepsEmpty(filters)
            },
        ],
        propertiesForUrl: [
            () => [selectors.filters],
            (filters: Partial<FilterType>) => {
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
        '/insights': (_: any, searchParams: Record<string, any>) => {
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

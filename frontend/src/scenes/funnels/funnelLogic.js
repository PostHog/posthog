import { kea } from 'kea'
import api from 'lib/api'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { objectsEqual, toParams } from 'lib/utils'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'

function wait(ms = 1000) {
    return new Promise((resolve) => {
        setTimeout(resolve, ms)
    })
}
const SECONDS_TO_POLL = 3 * 60

export async function pollFunnel(params = {}) {
    let result = await api.get('api/insight/funnel/?' + toParams(params))
    let start = window.performance.now()
    while (result.loading && (window.performance.now() - start) / 1000 < SECONDS_TO_POLL) {
        await wait()
        const { refresh: _, ...restParams } = params // eslint-disable-line
        result = await api.get('api/insight/funnel/?' + toParams(restParams))
    }
    // if endpoint is still loading after 3 minutes just return default
    if (result.loading) {
        throw { status: 0, statusText: 'Funnel timeout' }
    }
    return result
}

export const cleanFunnelParams = (filters) => {
    return {
        ...filters,
        ...(filters.date_from ? { date_from: filters.date_from } : {}),
        ...(filters.date_to ? { date_to: filters.date_to } : {}),
        ...(filters.actions ? { actions: filters.actions } : {}),
        ...(filters.events ? { events: filters.events } : {}),
        ...(filters.properties ? { properties: filters.properties } : {}),
        insight: ViewType.FUNNELS,
    }
}

const isStepsEmpty = (filters) => [...(filters.actions || []), ...(filters.events || [])].length === 0

export const funnelLogic = kea({
    actions: () => ({
        setSteps: (steps) => ({ steps }),
        clearFunnel: true,
        setFilters: (filters, refresh = false) => ({ filters, refresh }),
        loadFunnel: true,
        saveFunnelInsight: (name) => ({ name }),
    }),

    connect: {
        actions: [insightLogic, ['setAllFilters'], insightHistoryLogic, ['createInsight']],
    },

    loaders: () => ({
        people: {
            loadPeople: async (steps) => {
                return (await api.get('api/person/?uuid=' + steps[0].people.join(','))).results
            },
        },
    }),

    reducers: () => ({
        filters: [
            {},
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
            },
        ],
        stepsWithCountLoading: [
            false,
            {
                loadFunnel: () => true,
                setSteps: () => false,
            },
        ],
        people: {
            clearFunnel: () => null,
        },
    }),

    selectors: ({ selectors }) => ({
        peopleSorted: [
            () => [selectors.stepsWithCount, selectors.people],
            (steps, people) => {
                if (!people) {
                    return null
                }
                const score = (person) => {
                    return steps.reduce((val, step) => (step.people.indexOf(person.uuid) > -1 ? val + 1 : val), 0)
                }
                return people.sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [
            () => [selectors.filters],
            (filters) => {
                return isStepsEmpty(filters)
            },
        ],
        propertiesForUrl: [
            () => [selectors.filters],
            (filters) => {
                let result = {
                    insight: ViewType.FUNNELS,
                    ...cleanFunnelParams(filters),
                }
                return result
            },
        ],
    }),

    listeners: ({ actions, values, props }) => ({
        setSteps: async () => {
            if (values.stepsWithCount[0]?.people.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
        },
        setFilters: ({ refresh }) => {
            if (refresh) {
                actions.loadFunnel()
            }
            const cleanedParams = cleanFunnelParams(values.filters)
            actions.setAllFilters(cleanedParams)
        },
        loadFunnel: async () => {
            const cleanedParams = cleanFunnelParams(values.filters)

            actions.setAllFilters(cleanedParams)
            if (!props.dashboardItemId) {
                actions.createInsight({ ...cleanedParams, insight: ViewType.FUNNELS })
            }

            let result
            insightLogic.actions.startQuery()
            try {
                result = await pollFunnel(cleanedParams)
            } catch (e) {
                insightLogic.actions.endQuery(ViewType.FUNNELS, e)
                return []
            }
            insightLogic.actions.endQuery(ViewType.FUNNELS)
            actions.setSteps(result)
        },
        saveFunnelInsight: async ({ name }) => {
            await api.create('api/insight', {
                filters: values.filters,
                name,
                saved: true,
            })
        },
        clearFunnel: async () => {
            actions.setAllFilters({})
        },
    }),
    actionToUrl: ({ actions, values }) => ({
        [actions.setSteps]: () => ['/insights', values.propertiesForUrl],
        [actions.clearFunnel]: () => ['/insights', { insight: ViewType.FUNNELS }],
    }),
    urlToAction: ({ actions, values }) => ({
        '/insights': (_, searchParams) => {
            if (searchParams.insight === ViewType.FUNNELS) {
                const paramsToCheck = {
                    date_from: searchParams.date_from,
                    date_to: searchParams.date_to,
                    actions: searchParams.actions,
                    events: searchParams.events,
                    properties: searchParams.properties,
                }
                const _filters = {
                    date_from: values.filters.date_from,
                    date_to: values.filters.date_to,
                    actions: values.filters.actions,
                    events: values.filters.events,
                    properties: values.filters.properties,
                }

                if (!objectsEqual(_filters, paramsToCheck)) {
                    actions.setFilters(cleanFunnelParams(searchParams), !isStepsEmpty(paramsToCheck))
                }
            }
        },
    }),
})

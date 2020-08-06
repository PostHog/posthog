import { kea } from 'kea'
import api from 'lib/api'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { objectsEqual, toParams } from 'lib/utils'
import { insightHistoryLogic } from 'scenes/insights/InsightHistoryPanel/insightHistoryLogic'

export const cleanFunnelParams = (filters) => {
    return {
        ...(filters.date_from ? { date_from: filters.date_from } : {}),
        ...(filters.date_to ? { date_to: filters.date_to } : {}),
        ...(filters.actions ? { actions: filters.actions } : {}),
        ...(filters.events ? { events: filters.events } : {}),
        ...(filters.properties ? { properties: filters.properties } : {}),
    }
}

export const funnelLogic = kea({
    actions: () => ({
        setSteps: (steps) => ({ steps }),
        clearFunnel: true,
        setFilters: (filters, refresh = false) => ({ filters, refresh }),
        loadFunnel: true,
    }),

    connect: {
        actions: [insightLogic, ['setAllFilters'], insightHistoryLogic, ['createInsight']],
    },

    loaders: () => ({
        people: {
            loadPeople: async (steps) => {
                return (await api.get('api/person/?id=' + steps[0].people.join(','))).results
            },
        },
    }),

    reducers: () => ({
        filters: [
            {},
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
                clearFunnel: () => ({}),
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
                if (!people) return null
                const score = (person) => {
                    return steps.reduce((val, step) => (step.people.indexOf(person.id) > -1 ? val + 1 : val), 0)
                }
                return people.sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [
            () => [selectors.filters],
            (filters) => {
                return [...(filters.actions || []), ...(filters.events || [])].length === 0
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

    listeners: ({ actions, values }) => ({
        setSteps: async () => {
            if (values.stepsWithCount[0]?.people.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
        },
        setFilters: ({ refresh }) => {
            if (refresh) actions.loadFunnel()
        },
        loadFunnel: async () => {
            const cleanedParams = cleanFunnelParams(values.filters)

            actions.setAllFilters(cleanedParams)
            actions.createInsight({ ...cleanedParams, insight: ViewType.FUNNELS })

            const urlParams = toParams(cleanedParams)
            const result = await api.get('api/action/funnel/?' + urlParams)
            actions.setSteps(result)
        },
    }),
    actionToUrl: ({ actions, values }) => ({
        [actions.setSteps]: () => {
            return ['/insights', values.propertiesForUrl]
        },
        [actions.clearFunnel]: () => {
            return ['/insights', { insight: ViewType.FUNNELS }]
        },
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
                    actions.setFilters(paramsToCheck, true)
                }
            }
        },
    }),
})

import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { ViewType, insightLogic } from 'scenes/insights/insightLogic'
import { chartFilterLogic } from 'lib/components/ChartFilter/chartFilterLogic.js'
import { objectsEqual } from 'lib/utils'
import { FUNNEL_TRENDS } from 'lib/constants'

export const funnelLogic = kea({
    key: (props) => props.id || 'new',

    actions: () => ({
        setFunnel: (funnel, update) => ({ funnel, update }),
        clearFunnel: true,
    }),

    connect: {
        actions: [insightLogic, ['setAllFilters']],
        values: [chartFilterLogic, ['chartFilterFunnels']],
    },

    loaders: ({ props }) => ({
        funnel: [
            { filters: {} },
            {
                loadFunnel: async (id = props.id) => {
                    const funnel = await api.get('api/funnel/' + id + '/?exclude_count=1')
                    return funnel
                },
                updateFunnel: async (funnel) => {
                    return await api.update('api/funnel/' + funnel.id, funnel)
                },
                createFunnel: async (funnel) => {
                    return await api.create('api/funnel/', funnel)
                },
            },
        ],
        stepsWithCount: {
            loadStepsWithCount: async ({ id, refresh }) => {
                const extraQueryParams = {}
                extraQueryParams['refresh'] = refresh
                extraQueryParams['interval'] = insightLogic.values.allFilters.interval
                const extraQueryParamsString = extraQueryParams.length
                    ? `&${Object.entries(extraQueryParams)
                          .filter((pair) => ![undefined, null].includes(pair[0]))
                          .map((pair) => pair.join('='))
                          .join('&')}`
                    : ''
                const response = await api.get(`api/funnel/${id}/?display=FunnelSteps${extraQueryParamsString}`)
                return response.steps
            },
        },
        trends: {
            loadTrends: async ({ id, refresh }) => {
                const extraQueryParams = {}
                extraQueryParams['refresh'] = refresh
                extraQueryParams['interval'] = insightLogic.values.allFilters.interval
                const extraQueryParamsString = extraQueryParams.length
                    ? `&${Object.entries(extraQueryParams)
                          .filter((pair) => ![undefined, null].includes(pair[0]))
                          .map((pair) => pair.join('='))
                          .join('&')}`
                    : ''
                const response = await api.get(`api/funnel/${id}/?display=FunnelTrends${extraQueryParamsString}`)
                return response.trends
            },
        },
        people: {
            loadPeople: async (steps) => {
                return (await api.get('api/person/?id=' + steps[0].people.join(','))).results
            },
        },
    }),

    reducers: () => ({
        funnel: {
            setFunnel: (state, { funnel }) => ({
                ...state,
                ...funnel,
                filters: { ...state.filters, ...funnel.filters },
            }),
            clearFunnel: () => ({ filters: {} }),
        },
        stepsWithCount: {
            clearFunnel: () => null,
        },
        trends: {
            clearFunnel: () => null,
        },
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
            () => [selectors.funnel],
            (funnel) => {
                return funnel && [...(funnel.filters.actions || []), ...(funnel.filters.events || [])].length === 0
            },
        ],
    }),

    listeners: ({ actions, values }) => ({
        loadStepsWithCountSuccess: async () => {
            if (values.stepsWithCount[0]?.people.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
        },
        setFunnel: ({ update }) => {
            if (update) actions.updateFunnel(values.funnel)
        },
        loadFunnelSuccess: ({ funnel }) => {
            actions.setAllFilters({
                funnelId: funnel.id,
                name: funnel.name,
                date_from: funnel.filters.date_from,
                date_to: funnel.filters.date_to,
            })
        },
        updateFunnelSuccess: async ({ funnel }) => {
            const load = values.chartFilterFunnels === FUNNEL_TRENDS ? actions.loadTrends : actions.loadStepsWithCount
            load({ id: funnel.id, refresh: true })
            actions.setAllFilters({
                funnelId: funnel.id,
                name: funnel.name,
                date_from: funnel.filters.date_from,
                date_to: funnel.filters.date_to,
            })
            toast('Funnel saved!')
        },
        createFunnelSuccess: ({ funnel }) => {
            const load = values.chartFilterFunnels === FUNNEL_TRENDS ? actions.loadTrends : actions.loadStepsWithCount
            load({ id: funnel.id, refresh: true })
            actions.setAllFilters({
                funnelId: funnel.id,
                name: funnel.name,
                date_from: funnel.filters.date_from,
                date_to: funnel.filters.date_to,
            })
            toast('Funnel saved!')
        },
    }),
    actionToUrl: ({ actions }) => ({
        [actions.createFunnelSuccess]: ({ funnel }) => {
            return ['/insights', { id: funnel.id, insight: ViewType.FUNNELS }]
        },
        [actions.clearFunnel]: () => {
            return ['/insights', { insight: ViewType.FUNNELS }]
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '/insights': (_, searchParams) => {
            if (searchParams.insight === ViewType.FUNNELS) {
                const id = searchParams.id
                if (id != values.funnel.id) {
                    actions.loadFunnel(id)
                    const load =
                        values.chartFilterFunnels === FUNNEL_TRENDS ? actions.loadTrends : actions.loadStepsWithCount
                    load({ id })
                }

                const paramsToCheck = {
                    date_from: searchParams.date_from,
                    date_to: searchParams.date_to,
                    interval: searchParams.interval,
                }

                const _filters = {
                    date_from: values.funnel.filters.date_from,
                    date_to: values.funnel.filters.date_to,
                }

                if (!objectsEqual(_filters, paramsToCheck) && values.funnel.id) {
                    actions.setFunnel({ filters: paramsToCheck }, true)
                }
            }
        },
    }),
    events: ({ actions, key, props }) => ({
        afterMount: () => {
            if (key === 'new') {
                return
            }

            actions.loadFunnel()
            const load = values.chartFilterFunnels === FUNNEL_TRENDS ? actions.loadTrends : actions.loadStepsWithCount
            load({ id: props.id })
        },
    }),
})

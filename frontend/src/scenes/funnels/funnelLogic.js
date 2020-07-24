import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { ViewType, insightLogic } from 'scenes/trends/insightLogic'
import { objectsEqual } from 'lib/utils'

export const funnelLogic = kea({
    key: (props) => props.id || 'new',

    actions: () => ({
        setFunnel: (funnel, update) => ({ funnel, update }),
    }),

    connect: {
        actions: [insightLogic, ['setAllFilters']],
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
                    return await api.create('api/funnel', funnel)
                },
            },
        ],
        stepsWithCount: {
            loadStepsWithCount: async ({ id, refresh }) => {
                return (await api.get('api/funnel/' + id + (refresh ? '/?refresh=true' : ''))).steps
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
            if (values.stepsWithCount[0].people.length > 0) {
                actions.loadPeople(values.stepsWithCount)
            }
        },
        setFunnel: ({ update }) => {
            if (update) actions.updateFunnel(values.funnel)
        },
        loadFunnelSuccess: ({ funnel }) => {
            actions.setAllFilters(funnel.filters)
        },
        updateFunnelSuccess: async ({ funnel }) => {
            actions.loadStepsWithCount({ id: funnel.id, refresh: true })
            actions.setAllFilters(funnel.filters)
            toast('Funnel saved!')
        },
        createFunnelSuccess: ({ funnel }) => {
            actions.loadStepsWithCount({ id: funnel.id, refresh: true })
            actions.setAllFilters(funnel.filters)
            toast('Funnel saved!')
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/trends': (_, searchParams) => {
            if (searchParams.insight === ViewType.FUNNELS) {
                const id = searchParams.id
                if (id) {
                    actions.loadFunnel(id)
                    actions.loadStepsWithCount({ id })
                }

                const paramsToCheck = {
                    date_from: searchParams.date_from,
                    date_to: searchParams.date_to,
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
            actions.loadStepsWithCount({ id: props.id })
        },
    }),
})

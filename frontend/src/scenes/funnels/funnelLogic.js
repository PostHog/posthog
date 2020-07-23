import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { ViewType } from 'scenes/trends/trendsLogic'

export const funnelLogic = kea({
    key: (props) => props.id || 'new',

    actions: () => ({
        setFunnel: (funnel, update) => ({ funnel, update }),
    }),

    loaders: ({ props }) => ({
        funnel: [
            { filters: {} },
            {
                loadFunnel: async (id = props.id) => {
                    return await api.get('api/funnel/' + id + '/?exclude_count=1')
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
        updateFunnelSuccess: async ({ funnel }) => {
            actions.loadStepsWithCount({ id: funnel.id, refresh: true })
            toast('Funnel saved!')
        },
        createFunnelSuccess: ({ funnel }) => {
            actions.loadStepsWithCount({ id: funnel.id, refresh: true })
            toast('Funnel saved!')
        },
    }),
    urlToAction: ({ actions }) => ({
        '/trends': (_, searchParams) => {
            if (searchParams.insight === ViewType.FUNNELS) {
                const id = searchParams.id
                if (id) {
                    actions.loadFunnel(id)
                    actions.loadStepsWithCount({ id })
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

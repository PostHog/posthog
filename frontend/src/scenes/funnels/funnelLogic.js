import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'

export const funnelLogic = kea({
    actions: () => ({
        setFunnel: (funnel, update) => ({ funnel, update }),
    }),
    loaders: ({ props, values }) => ({
        funnel: {
            loadFunnel: async (id = props.id) => {
                return await api.get('api/funnel/' + id + '/?exclude_count=1')
            },
            updateFunnel: async funnel => {
                return await api.update('api/funnel/' + funnel.id, funnel)
            },
            createFunnel: async funnel => {
                return await api.create('api/funnel', funnel)
            },
        },
        stepsWithCount: {
            loadStepsWithCount: async (id = props.id) => {
                return (await api.get('api/funnel/' + id)).steps
            },
        },
        people: {
            loadPeople: async steps => {
                return (await api.get('api/person/?id=' + steps[0].people.join(','))).results
            },
        },
    }),
    reducers: ({ actions }) => ({
        funnel: [
            {},
            {
                [actions.setFunnel]: (state, { funnel }) => ({
                    ...state,
                    ...funnel,
                    filters: { ...state.filters, ...funnel.filters },
                }),
                [actions.loadFunnelSuccess]: (state, { funnel }) => funnel,
                [actions.createFunnelSuccess]: (state, { funnel }) => funnel,
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        peopleSorted: [
            () => [selectors.stepsWithCount, selectors.people],
            (steps, people) => {
                if (!people) return null
                const score = person => {
                    return steps.reduce((val, step) => (step.people.indexOf(person.id) > -1 ? val + 1 : val), 0)
                }
                return people.sort((a, b) => score(b) - score(a))
            },
        ],
        isStepsEmpty: [
            () => [selectors.funnel],
            funnel => {
                return funnel && [...(funnel.filters.actions || []), ...(funnel.filters.events || [])].length == 0
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.loadStepsWithCountSuccess]: async () => {
            actions.loadPeople(values.stepsWithCount)
        },
        [actions.setFunnel]: ({ update }) => {
            if (update) actions.updateFunnel(values.funnel)
        },
        [actions.updateFunnelSuccess]: async ({ funnel }) => {
            actions.loadStepsWithCount(funnel.id)
            toast('Funnel saved!')
        },
        [actions.createFunnelSuccess]: ({ funnel }) => {
            actions.loadStepsWithCount(funnel.id)
            toast('Funnel saved!')
        },
    }),

    actionToUrl: ({ actions }) => ({
        [actions.createFunnelSuccess]: ({ funnel }) => '/funnel/' + funnel.id,
    }),

    events: ({ actions, props }) => ({
        afterMount: () => {
            if (!props.id) return actions.loadFunnelSuccess({ filters: {} })
            actions.loadFunnel()
            actions.loadStepsWithCount()
        },
    }),
})

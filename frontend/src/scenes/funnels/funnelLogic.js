import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils'

export const funnelLogic = kea({
    key: props => props.id,
    actions: () => ({
        setFilters: filters => ({ filters }),
        setSteps: steps => ({ steps }),
        funnelUpdateRequest: (funnel, callback) => ({ funnel, callback }),
        funnelUpdateFailure: (updateKey, error) => ({ updateKey, error }),
        setFunnel: funnel => ({ funnel }),
    }),
    loaders: ({ props, values }) => ({
        funnel: {
            loadFunnel: async (id = props.id) => {
                return await api.get('api/funnel/' + id + '/?exclude_count=1')
            },
        },
        stepsWithCount: {
            loadStepsWithCount: async (id = props.id) => {
                return (await api.get('api/funnel/' + id + '/?' + toParams(values.filters))).steps
            },
        },
        people: {
            loadPeople: async steps => {
                return (await api.get('api/person/?id=' + steps[0].people.join(','))).results
            },
        },
    }),
    reducers: ({ actions }) => ({
        filters: [
            {},
            {
                [actions.setFilters]: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
            },
        ],
        funnel: [
            {},
            {
                [actions.setFunnel]: (state, { funnel }) => ({ ...state, ...funnel }),
                [actions.loadFunnelSuccess]: (state, { funnel }) => funnel,
            },
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.loadStepsWithCountSuccess]: async () => {
            actions.loadPeople(values.stepsWithCount)
        },
        [actions.setFilters]: async () => {
            actions.loadStepsWithCount()
        },
        [actions.funnelUpdateRequest]: async ({ funnel, callback }) => {
            const newFunnel = await api.update('api/funnel/' + funnel.id, funnel)
            // Question: Can I somehow have the loader plugin catch errors here?
            actions.loadStepsWithCount()
            callback(newFunnel)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFunnel()
            actions.loadStepsWithCount()
        },
    }),
})

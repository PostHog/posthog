import { kea } from 'kea'
import api from 'lib/api'
import { toParams } from 'lib/utils';



export const funnelLogic = kea({
    key: props => props.id,
    actions: () => ({
        setFilters: filters => ({ filters })
    }),
    loaders: ({ props, values }) => ({
        funnel: {
            loadFunnel: async (id = props.id) => {
                return await api.get('api/funnel/' + id + '/?exclude_count=1')
            },
        },
        steps: {
            loadSteps: async (id = props.id) => {
                return (await api.get('api/funnel/' + id + '/?' + toParams(values.filters))).steps
            },
        },
        people: {
            loadPeople: async (steps) => {
                return (await api.get('api/person/?id=' + steps[0].people.join(','))).results
            }
        },
    }),
    reducers: ({ actions }) => ({
        filters: [
            {},
            {
                [actions.setFilters]: (state, { filters }) => ({
                    ...state,
                    ...filters
                })
            }
        ],
    }),
    listeners: ({ actions, values }) => ({
        [actions.loadStepsSuccess]: async () => {
            actions.loadPeople(values.steps)
        },
        [actions.setFilters]: async () => {
            actions.loadSteps()
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFunnel()
            actions.loadSteps()
        }
    }),
})

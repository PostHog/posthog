import { kea } from 'kea'
import api from 'lib/api'

export const dashboardLogic = kea({
    key: props => props.id,

    loaders: ({ props }) => ({
        dashboard: [
            {},
            {
                loadDashboard: async () => {
                    return await api.get(`api/dashboard/${props.id}`)
                },
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        items: [() => [selectors.dashboard], dashboard => dashboard.items || []],
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadDashboard],
    }),
})

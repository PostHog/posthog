import { kea } from 'kea'
import api from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'

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

    selectors: ({ selectors, props }) => ({
        items: [() => [selectors.dashboard], dashboard => dashboard.items || []],
        partialDashboard: [
            () => [dashboardsModel.selectors.dashboards, selectors.dashboard],
            (dashboards, dashboard) =>
                Object.assign({}, dashboards.find(d => d.id === parseInt(props.id)) || {}, dashboard),
        ],
    }),

    events: ({ actions }) => ({
        afterMount: [actions.loadDashboard],
    }),
})

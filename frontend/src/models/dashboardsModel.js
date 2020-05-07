import { kea } from 'kea'
import api from 'lib/api'

export const dashboardsModel = kea({
    loaders: () => ({
        dashboards: [
            [],
            {
                loadDashboards: async () => (await api.get('api/dashboards')).results,
            },
        ],
    }),
    selectors: ({ selectors }) => ({
        pinnedDashboards: [() => [selectors.dashboards], dashboards => dashboards.filter(d => d.pinned)],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadDashboards,
    }),
})

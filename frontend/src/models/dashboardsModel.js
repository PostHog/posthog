import { kea } from 'kea'
import api from 'lib/api'

export const dashboardsModel = kea({
    loaders: () => ({
        rawDashboards: [
            [],
            {
                loadDashboards: async () => (await api.get('api/dashboard')).results,
            },
        ],
        newDashboard: {
            addDashboard: async ({ name }) => await api.create('api/dashboard', { name }),
        },
    }),

    reducers: () => ({
        rawDashboards: {
            addDashboardSuccess: (state, { newDashboard }) => [...state, newDashboard],
        },
    }),

    selectors: ({ selectors }) => ({
        dashboards: [
            () => [selectors.rawDashboards],
            rawDashboards => rawDashboards.sort((a, b) => a.name.localeCompare(b.name)),
        ],
        pinnedDashboards: [() => [selectors.dashboards], dashboards => dashboards.filter(d => d.pinned)],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadDashboards,
    }),
})

import { kea } from 'kea'
import api from 'lib/api'
import { idToKey } from 'lib/utils'

export const dashboardsModel = kea({
    loaders: () => ({
        rawDashboards: [
            {},
            {
                loadDashboards: async () => {
                    const { results } = await api.get('api/dashboard')
                    return idToKey(results)
                },
            },
        ],
        // We're not using this loader as a reducer per se, but just calling it `dashboard`
        // to have the right payload ({ dashboard }) in the Success actions
        dashboard: {
            addDashboard: async ({ name }) => await api.create('api/dashboard', { name }),
            renameDashboard: async ({ id, name }) => await api.update(`api/dashboard/${id}`, { name }),
            pinDashboard: async id => await api.update(`api/dashboard/${id}`, { pinned: true }),
            unpinDashboard: async id => await api.update(`api/dashboard/${id}`, { pinned: false }),
        },
    }),

    reducers: () => ({
        rawDashboards: {
            addDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            renameDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            pinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            unpinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
        },
    }),

    selectors: ({ selectors }) => ({
        dashboards: [
            () => [selectors.rawDashboards],
            rawDashboards => Object.values(rawDashboards).sort((a, b) => a.name.localeCompare(b.name)),
        ],
        pinnedDashboards: [() => [selectors.dashboards], dashboards => dashboards.filter(d => d.pinned)],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadDashboards,
    }),
})

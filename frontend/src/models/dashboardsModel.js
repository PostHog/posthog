import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { delay, idToKey } from 'lib/utils'

export const dashboardsModel = kea({
    actions: () => ({
        delayedDeleteDashboard: id => ({ id }),
        setLastVisitedDashboardId: id => ({ id }),
    }),
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
            deleteDashboard: async id => {
                await api.delete(`api/dashboard/${id}`)
                return { id }
            },
            pinDashboard: async id => await api.update(`api/dashboard/${id}`, { pinned: true }),
            unpinDashboard: async id => await api.update(`api/dashboard/${id}`, { pinned: false }),
        },
    }),

    reducers: () => ({
        rawDashboards: {
            addDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            renameDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            deleteDashboardSuccess: state => state, // give us time to leave the page
            delayedDeleteDashboard: (state, { id }) => {
                const { [id]: _discard, ...rest } = state
                return rest
            },
            pinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            unpinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
        },
        lastVisitedDashboardId: [
            null,
            {
                setLastVisitedDashboardId: (_, { id }) => id,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        dashboards: [
            () => [selectors.rawDashboards],
            rawDashboards => {
                const list = Object.values(rawDashboards).sort((a, b) => a.name.localeCompare(b.name))
                return [...list.filter(d => d.pinned), ...list.filter(d => !d.pinned)]
            },
        ],
        pinnedDashboards: [() => [selectors.dashboards], dashboards => dashboards.filter(d => d.pinned)],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadDashboards,
    }),

    listeners: ({ actions, values }) => ({
        deleteDashboardSuccess: async ({ dashboard }) => {
            const { id } = dashboard
            const nextDashboard = [...values.pinnedDashboards, ...values.dashboards].filter(d => d.id !== id)[0]
            if (nextDashboard) {
                router.actions.push(`/dashboard/${nextDashboard.id}`)
            } else {
                router.actions.push('/dashboard')
            }
            await delay(500)
            actions.delayedDeleteDashboard(id)
        },
    }),

    urlToAction: ({ actions }) => ({
        '/dashboard/:id': ({ id }) => actions.setLastVisitedDashboardId(parseInt(id)),
    }),
})

import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { delay, idToKey } from 'lib/utils'
import React from 'react'
import { toast } from 'react-toastify'

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
            addDashboard: async ({ name }) => await api.create('api/dashboard', { name, pinned: true }),
            restoreDashboard: async dashboard => await api.create('api/dashboard', dashboard),
            renameDashboard: async ({ id, name }) => await api.update(`api/dashboard/${id}`, { name }),
            deleteDashboard: async id => {
                const dashboard = await api.get(`api/dashboard/${id}`)
                await api.delete(`api/dashboard/${id}`)
                return dashboard
            },
            pinDashboard: async id => await api.update(`api/dashboard/${id}`, { pinned: true }),
            unpinDashboard: async id => await api.update(`api/dashboard/${id}`, { pinned: false }),
        },
    }),

    reducers: () => ({
        rawDashboards: {
            addDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            restoreDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            renameDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            deleteDashboardSuccess: (state, { dashboard }) => ({
                ...state,
                [dashboard.id]: { ...state[dashboard.id], deleted: true },
            }),
            delayedDeleteDashboard: (state, { id }) => {
                // this gives us time to leave the /dashboard/:deleted_id page
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
        dashboardsLoading: [() => [selectors.rawDashboardsLoading], rawDashboardsLoading => rawDashboardsLoading],
        pinnedDashboards: [() => [selectors.dashboards], dashboards => dashboards.filter(d => d.pinned)],
    }),

    events: ({ actions }) => ({
        afterMount: actions.loadDashboards,
    }),

    listeners: ({ actions, values }) => ({
        addDashboardSuccess: ({ dashboard }) => {
            toast(`Dashboard "${dashboard.name}" created!`)
        },

        restoreDashboardSuccess: ({ dashboard }) => {
            toast(`Dashboard "${dashboard.name}" restored!`)
            router.actions.push(`/dashboard/${dashboard.id}`)
        },

        deleteDashboardSuccess: async ({ dashboard }) => {
            const toastId = toast(
                <span>
                    Dashboard "{dashboard.name}" deleted!{' '}
                    <a
                        href="#"
                        onClick={e => {
                            e.preventDefault()
                            actions.restoreDashboard(dashboard)
                            toast.dismiss(toastId)
                        }}
                    >
                        Undo
                    </a>
                </span>
            )

            const { id } = dashboard
            const nextDashboard = [...values.pinnedDashboards, ...values.dashboards].find(
                d => d.id !== id && !d.deleted
            )
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

import * as React from 'react'
import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { delay, idToKey } from 'lib/utils'
import { toast } from 'react-toastify'
import { dashboardsModelType } from '~/models/dashboardsModelType'

interface Dashboard {
    created_at: string
    created_by: number
    deleted: boolean
    id: number
    is_shared: boolean
    items: DashboardItem[]
    name: string
    pinned: boolean
    share_token: string
}

type LayoutKey = 'lg' | 'sm' | 'xs' | 'xxs'

interface DashboardItem {
    color: string
    dashboard: number
    deleted: boolean
    // filters: {,…}
    // funnel: null
    id: string
    last_refresh: string
    layouts: Record<LayoutKey, { h: number; w: number; x: number; y: number }>
    name: string
    // order: null
    // refreshing: true
    // result: null
    type: string
}

export const dashboardsModel = kea<dashboardsModelType<Dashboard, DashboardItem>>({
    actions: () => ({
        delayedDeleteDashboard: (id: number) => ({ id }),
        setLastVisitedDashboardId: (id: number) => ({ id }),
        // this is moved out of dashboardLogic, so that you can click "undo" on a item move when already
        // on another dashboard - both dashboards can listen to and share this event, even if one is not yet mounted
        updateDashboardItem: (item: DashboardItem) => ({ item }),
    }),
    loaders: () => ({
        rawDashboards: [
            {} as Record<string, Dashboard>,
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
            __default: null as Dashboard | null,
            addDashboard: async ({ name }: { name: string }) =>
                await api.create('api/dashboard', { name, pinned: true }),
            renameDashboard: async ({ id, name }: { id: number; name: string }) =>
                await api.update(`api/dashboard/${id}`, { name }),
            deleteDashboard: async ({ id }: { id: number }) =>
                await api.update(`api/dashboard/${id}`, { deleted: true }),
            restoreDashboard: async ({ id }: { id: number }) =>
                await api.update(`api/dashboard/${id}`, { deleted: false }),
            pinDashboard: async (id: number) => await api.update(`api/dashboard/${id}`, { pinned: true }),
            unpinDashboard: async (id: number) => await api.update(`api/dashboard/${id}`, { pinned: false }),
        },
    }),

    reducers: () => ({
        redirect: [
            true,
            {
                deleteDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
                restoreDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
            },
        ],
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
                const { [id]: _discard, ...rest } = state // eslint-disable-line
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
            (rawDashboards) => {
                const list = Object.values(rawDashboards).sort((a, b) => a.name.localeCompare(b.name))
                return [...list.filter((d) => d.pinned), ...list.filter((d) => !d.pinned)]
            },
        ],
        dashboardsLoading: [() => [selectors.rawDashboardsLoading], (rawDashboardsLoading) => rawDashboardsLoading],
        pinnedDashboards: [() => [selectors.dashboards], (dashboards) => dashboards.filter((d) => d.pinned)],
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
            if (values.redirect) {
                router.actions.push(`/dashboard/${dashboard.id}`)
            }
        },

        deleteDashboardSuccess: async ({ dashboard }) => {
            const toastId = toast(
                <span>
                    Dashboard "{dashboard.name}" deleted!{' '}
                    <a
                        href="#"
                        onClick={(e) => {
                            e.preventDefault()
                            actions.restoreDashboard({ id: dashboard.id, redirect: values.redirect })
                            toast.dismiss(toastId)
                        }}
                    >
                        Undo
                    </a>
                </span>
            )

            const { id } = dashboard
            const nextDashboard = [...values.pinnedDashboards, ...values.dashboards].find(
                (d) => d.id !== id && !d.deleted
            )

            if (values.redirect) {
                if (nextDashboard) {
                    router.actions.push(`/dashboard/${nextDashboard.id}`)
                } else {
                    router.actions.push('/dashboard')
                }

                await delay(500)
            }

            actions.delayedDeleteDashboard(id)
        },
    }),

    urlToAction: ({ actions }) => ({
        '/dashboard/:id': ({ id }) => actions.setLastVisitedDashboardId(parseInt(id)),
    }),
})

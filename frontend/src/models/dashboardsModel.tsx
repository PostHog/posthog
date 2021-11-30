import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { delay, idToKey, setPageTitle } from 'lib/utils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React from 'react'
import { toast } from 'react-toastify'
import { dashboardsModelType } from './dashboardsModelType'
import { DashboardItemType, DashboardType, InsightShortId } from '~/types'
import { urls } from 'scenes/urls'
import { teamLogic } from 'scenes/teamLogic'

export const dashboardsModel = kea<dashboardsModelType>({
    path: ['models', 'dashboardsModel'],
    actions: () => ({
        delayedDeleteDashboard: (id: number) => ({ id }),
        setDiveSourceId: (id: InsightShortId | null) => ({ id }),
        setLastDashboardId: (id: number) => ({ id }),
        // this is moved out of dashboardLogic, so that you can click "undo" on a item move when already
        // on another dashboard - both dashboards can listen to and share this event, even if one is not yet mounted
        updateDashboardItem: (item: Partial<DashboardItemType>) => ({ item }),
        // a side effect on this action exists in dashboardLogic so that individual refresh statuses can be bubbled up
        // to dashboard items in dashboards
        updateDashboardRefreshStatus: (
            shortId: string | undefined | null,
            refreshing: boolean | null,
            last_refresh: string | null
        ) => ({
            shortId,
            refreshing,
            last_refresh,
        }),
        pinDashboard: (id: number, source: DashboardEventSource) => ({ id, source }),
        unpinDashboard: (id: number, source: DashboardEventSource) => ({ id, source }),
        loadDashboards: true,
        loadSharedDashboard: (shareToken: string) => ({ shareToken }),
        addDashboard: ({ name, show, useTemplate }: { name: string; show?: boolean; useTemplate?: string }) => ({
            name,
            show: show || false,
            useTemplate: useTemplate || '',
        }),
        duplicateDashboard: ({ id, name, show }: { id: number; name?: string; show?: boolean }) => ({
            id: id,
            name: name || `#${id}`,
            show: show || false,
        }),
    }),
    loaders: ({ values }) => ({
        rawDashboards: [
            {} as Record<string, DashboardType>,
            {
                loadDashboards: async (_, breakpoint) => {
                    await breakpoint(50)
                    const { results } = await api.get(`api/projects/${teamLogic.values.currentTeamId}/dashboards/`)
                    return idToKey(results)
                },
            },
        ],
        sharedDashboard: [
            null as DashboardType | null,
            {
                loadSharedDashboard: async ({ shareToken }) => {
                    return await api.get(`api/shared_dashboards/${shareToken}`)
                },
            },
        ],
        // We're not using this loader as a reducer per se, but just calling it `dashboard`
        // to have the right payload ({ dashboard }) in the Success actions
        dashboard: {
            __default: null as null | DashboardType,
            addDashboard: async ({ name, show, useTemplate }) => {
                const result = (await api.create(`api/projects/${teamLogic.values.currentTeamId}/dashboards/`, {
                    name,
                    use_template: useTemplate,
                })) as DashboardType
                if (show) {
                    router.actions.push(urls.dashboard(result.id))
                }
                return result
            },
            updateDashboard: async ({ id, ...payload }, breakpoint) => {
                if (!Object.entries(payload).length) {
                    return
                }
                await breakpoint(700)
                const response = (await api.update(
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`,
                    payload
                )) as DashboardType
                const updatedAttribute = Object.keys(payload)[0]
                if (updatedAttribute === 'name' || updatedAttribute === 'description' || updatedAttribute === 'tags') {
                    eventUsageLogic.actions.reportDashboardFrontEndUpdate(
                        updatedAttribute,
                        values.rawDashboards[id]?.[updatedAttribute]?.length || 0,
                        payload[updatedAttribute].length
                    )
                    if (updatedAttribute === 'name') {
                        setPageTitle(response.name ? `${response.name} • Dashboard` : 'Dashboard')
                    }
                }
                return response
            },
            setIsSharedDashboard: async ({ id, isShared }) =>
                (await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`, {
                    is_shared: isShared,
                })) as DashboardType,
            deleteDashboard: async ({ id }) =>
                (await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`, {
                    deleted: true,
                })) as DashboardType,
            restoreDashboard: async ({ id }) =>
                (await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`, {
                    deleted: false,
                })) as DashboardType,
            pinDashboard: async ({ id, source }) => {
                const response = (await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`, {
                    pinned: true,
                })) as DashboardType
                eventUsageLogic.actions.reportDashboardPinToggled(true, source)
                return response
            },
            unpinDashboard: async ({ id, source }) => {
                const response = (await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`, {
                    pinned: false,
                })) as DashboardType
                eventUsageLogic.actions.reportDashboardPinToggled(false, source)
                return response
            },
            duplicateDashboard: async ({ id, name, show }) => {
                const result = (await api.create(`api/projects/${teamLogic.values.currentTeamId}/dashboards/`, {
                    use_dashboard: id,
                    name: `${name} (Copy)`,
                })) as DashboardType
                if (show) {
                    router.actions.push(urls.dashboard(result.id))
                }
                return result
            },
        },
    }),

    reducers: {
        redirect: [
            true,
            {
                deleteDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
                restoreDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
            },
        ],
        rawDashboards: {
            // NB! Kea-TypeGen assignes the type of the reducer to the abcSuccess actions.
            // This means we must get rid of the `| null` manually until it's fixed:
            // https://github.com/keajs/kea-typegen/issues/10
            addDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            restoreDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
            updateDashboardSuccess: (state, { dashboard }) =>
                dashboard ? { ...state, [dashboard.id]: dashboard } : state,
            setIsSharedDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
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
            duplicateDashboardSuccess: (state, { dashboard }) => ({
                ...state,
                [dashboard.id]: { ...dashboard, _highlight: true },
            }),
        },
        lastDashboardId: [
            null as null | number,
            { persist: true },
            {
                setLastDashboardId: (_, { id }) => id,
            },
        ],
        diveSourceId: [
            null as InsightShortId | null,
            {
                setDiveSourceId: (_, { id }) => id,
            },
        ],
    },

    selectors: ({ selectors }) => ({
        nameSortedDashboards: [
            () => [selectors.rawDashboards],
            (rawDashboards) => {
                return [...Object.values(rawDashboards)].sort((a, b) =>
                    (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')
                )
            },
        ],
        /** Display dashboards are additionally sorted by pin status: pinned first. */
        pinSortedDashboards: [
            () => [selectors.nameSortedDashboards],
            (nameSortedDashboards) => {
                return [...nameSortedDashboards].sort(
                    (a, b) =>
                        (Number(b.pinned) - Number(a.pinned)) * 10 +
                        (a.name ?? 'Untitled').localeCompare(b.name ?? 'Untitled')
                )
            },
        ],
        dashboardsLoading: [
            () => [selectors.rawDashboardsLoading, selectors.sharedDashboardLoading],
            (dashesLoading, sharedLoading) => dashesLoading || sharedLoading,
        ],
        pinnedDashboards: [
            () => [selectors.nameSortedDashboards],
            (nameSortedDashboards) => nameSortedDashboards.filter((d) => d.pinned),
        ],
    }),

    events: ({ actions }) => ({
        afterMount: () => actions.loadDashboards(),
    }),

    listeners: ({ actions, values }) => ({
        addDashboardSuccess: ({ dashboard }) => {
            toast(`Dashboard "${dashboard.name}" created!`)
        },

        restoreDashboardSuccess: ({ dashboard }) => {
            toast(`Dashboard "${dashboard.name}" restored!`)
            if (values.redirect) {
                router.actions.push(urls.dashboard(dashboard.id))
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
            const nextDashboard = values.pinSortedDashboards.find((d) => d.id !== id && !d.deleted)

            if (values.redirect) {
                if (nextDashboard) {
                    router.actions.push(urls.dashboard(nextDashboard.id))
                } else {
                    router.actions.push(urls.dashboards())
                }

                await delay(500)
            }

            actions.delayedDeleteDashboard(id)
        },

        duplicateDashboardSuccess: async ({ dashboard }) => {
            toast(`Dashboard copied as "${dashboard.name}"!`)
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '/dashboard/:id': ({ id }, { dive_source_id: diveSourceId }) => {
            if (id) {
                actions.setLastDashboardId(parseInt(id))
            }
            if (diveSourceId !== undefined && diveSourceId !== null) {
                actions.setDiveSourceId(diveSourceId)
            } else if (values.diveSourceId !== null) {
                actions.setDiveSourceId(null)
            }
        },
    }),
})

import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api, { PaginatedResponse } from 'lib/api'
import { GENERATED_DASHBOARD_PREFIX } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { idToKey, isUserLoggedIn } from 'lib/utils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { tagsModel } from '~/models/tagsModel'
import { DashboardBasicType, DashboardTile, DashboardType, InsightShortId, QueryBasedInsightModel } from '~/types'

import type { dashboardsModelType } from './dashboardsModelType'

export const dashboardsModel = kea<dashboardsModelType>([
    path(['models', 'dashboardsModel']),
    connect({
        actions: [tagsModel, ['loadTags']],
    }),
    actions(() => ({
        // we page through the dashboards and need to manually track when that is finished
        dashboardsFullyLoaded: true,
        delayedDeleteDashboard: (id: number) => ({ id }),
        setDiveSourceId: (id: InsightShortId | null) => ({ id }),
        addDashboardSuccess: (dashboard: DashboardType) => ({ dashboard }),
        // this is moved out of dashboardLogic, so that you can click "undo" on an item move when already
        // on another dashboard - both dashboards can listen to and share this event, even if one is not yet mounted
        // can provide extra dashboard ids if not all listeners will choose to respond to this action
        // not providing a dashboard id is a signal that only listeners in the item.dashboards array should respond
        // specifying `number` not `Pick<DashboardType, 'id'> because kea typegen couldn't figure out the import in `savedInsightsLogic`
        // if an update is made against an insight it will hold color in dashboard context
        updateDashboardInsight: (insight: QueryBasedInsightModel, extraDashboardIds?: number[]) => ({
            insight,
            extraDashboardIds,
        }),
        pinDashboard: (id: number, source: DashboardEventSource) => ({ id, source }),
        unpinDashboard: (id: number, source: DashboardEventSource) => ({ id, source }),
        duplicateDashboard: ({
            id,
            name,
            show,
            duplicateTiles,
        }: {
            id: number
            name?: string
            show?: boolean
            duplicateTiles?: boolean
        }) => ({
            id: id,
            name: name || `#${id}`,
            show: show || false,
            duplicateTiles: duplicateTiles || false,
        }),
        tileMovedToDashboard: (tile: DashboardTile, dashboardId: number) => ({ tile, dashboardId }),
        tileRemovedFromDashboard: ({ tile, dashboardId }: { tile?: DashboardTile; dashboardId?: number }) => ({
            tile,
            dashboardId,
        }),
        tileAddedToDashboard: (dashboardId: number) => ({ dashboardId }),
    })),
    loaders(({ values, actions }) => ({
        pagedDashboards: [
            null as PaginatedResponse<DashboardBasicType> | null,
            {
                loadDashboards: async (url?: string) => {
                    // looking at a fully exported dashboard, return its contents
                    const exportedDashboard = window.POSTHOG_EXPORTED_DATA?.dashboard
                    if (exportedDashboard?.id && exportedDashboard?.tiles) {
                        return { count: 1, next: null, previous: null, results: [exportedDashboard] }
                    }

                    if (!isUserLoggedIn()) {
                        // If user is anonymous (i.e. viewing a shared dashboard logged out), don't load authenticated stuff
                        return { count: 0, next: null, previous: null, results: [] }
                    }
                    return await api.get(url || `api/projects/${teamLogic.values.currentTeamId}/dashboards/?limit=100`)
                },
            },
        ],
        // We're not using this loader as a reducer per se, but just calling it `dashboard`
        // to have the right payload ({ dashboard }) in the Success actions
        dashboard: {
            __default: null as null | DashboardType,
            updateDashboard: async ({ id, allowUndo, ...payload }, breakpoint) => {
                if (!Object.entries(payload).length) {
                    return
                }
                breakpoint()

                const beforeChange = { ...values.rawDashboards[id] }

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
                    if (updatedAttribute === 'tags') {
                        actions.loadTags()
                    }
                }
                if (allowUndo) {
                    lemonToast.success('Dashboard updated', {
                        button: {
                            label: 'Undo',
                            action: async () => {
                                const reverted = (await api.update(
                                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`,
                                    beforeChange
                                )) as DashboardType
                                actions.updateDashboardSuccess(reverted)
                                lemonToast.success('Dashboard change reverted')
                            },
                        },
                    })
                }
                return response
            },
            deleteDashboard: async ({ id, deleteInsights }) =>
                (await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}`, {
                    deleted: true,
                    delete_insights: deleteInsights,
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
            duplicateDashboard: async ({ id, name, show, duplicateTiles }) => {
                const result = (await api.create(`api/projects/${teamLogic.values.currentTeamId}/dashboards/`, {
                    use_dashboard: id,
                    name: `${name} (Copy)`,
                    duplicate_tiles: duplicateTiles,
                })) as DashboardType
                if (show) {
                    router.actions.push(urls.dashboard(result.id))
                }
                return result
            },
        },
    })),
    reducers({
        pagingDashboardsCompleted: [
            false,
            {
                dashboardsFullyLoaded: () => true,
            },
        ],
        redirect: [
            true,
            {
                deleteDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
                restoreDashboard: (state, { redirect }) => (typeof redirect !== 'undefined' ? redirect : state),
            },
        ],
        rawDashboards: [
            {} as Record<string, DashboardBasicType | DashboardType>,
            {
                loadDashboardsSuccess: (state, { pagedDashboards }) => {
                    if (!pagedDashboards) {
                        return state
                    }
                    return { ...state, ...idToKey(pagedDashboards.results) }
                },
                // NB! Kea-TypeGen assignes the type of the reducer to the abcSuccess actions.
                // This means we must get rid of the `| null` manually until it's fixed:
                // https://github.com/keajs/kea-typegen/issues/10
                addDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
                restoreDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
                updateDashboardSuccess: (state, { dashboard }) =>
                    dashboard ? { ...state, [dashboard.id]: dashboard } : state,
                deleteDashboardSuccess: (state, { dashboard }) => ({
                    ...state,
                    [dashboard.id]: { ...state[dashboard.id], deleted: true },
                }),
                delayedDeleteDashboard: (state, { id }) => {
                    // This gives us time to leave the /dashboard/:deleted_id page
                    const { [id]: _discard, ...rest } = state
                    return rest
                },
                pinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
                unpinDashboardSuccess: (state, { dashboard }) => ({ ...state, [dashboard.id]: dashboard }),
                duplicateDashboardSuccess: (state, { dashboard }) => ({
                    ...state,
                    [dashboard.id]: { ...dashboard, _highlight: true },
                }),
            },
        ],
    }),
    selectors(({ selectors }) => ({
        nameSortedDashboards: [
            () => [selectors.rawDashboards],
            (rawDashboards) => {
                return [...Object.values(rawDashboards)]
                    .filter((dashboard) => !(dashboard.name ?? 'Untitled').startsWith(GENERATED_DASHBOARD_PREFIX))
                    .sort(nameCompareFunction)
            },
        ],
        /** Display dashboards are additionally sorted by pin status: pinned first. */
        pinSortedDashboards: [
            () => [selectors.nameSortedDashboards],
            (nameSortedDashboards) => {
                return [...nameSortedDashboards].sort(
                    (a, b) => (Number(b.pinned) - Number(a.pinned)) * 10 + nameCompareFunction(a, b)
                )
            },
        ],
        dashboardsLoading: [
            () => [selectors.pagedDashboardsLoading, selectors.pagingDashboardsCompleted],
            (pagedDashboardsLoading, pagingDashboardsCompleted) => pagedDashboardsLoading || !pagingDashboardsCompleted,
        ],
        pinnedDashboards: [
            () => [selectors.nameSortedDashboards],
            (nameSortedDashboards) => nameSortedDashboards.filter((d) => d.pinned),
        ],
    })),
    listeners(({ actions, values }) => ({
        loadDashboardsSuccess: ({ pagedDashboards }) => {
            if (pagedDashboards?.next) {
                actions.loadDashboards(pagedDashboards.next)
            } else {
                actions.dashboardsFullyLoaded()
            }
        },
        addDashboardSuccess: ({ dashboard }) => {
            lemonToast.success(<>Dashboard created</>, {
                button: {
                    label: 'View',
                    action: () => router.actions.push(urls.dashboard(dashboard.id)),
                },
            })
        },

        restoreDashboardSuccess: ({ dashboard }) => {
            lemonToast.success(
                <>
                    Dashboard <b>{dashboard.name}</b> restored
                </>
            )
            if (values.redirect) {
                router.actions.push(urls.dashboard(dashboard.id))
            }
        },

        deleteDashboardSuccess: async ({ dashboard }) => {
            lemonToast.success(
                <>
                    Dashboard <b>{dashboard.name}</b> deleted
                </>,
                {
                    button: {
                        label: 'Undo',
                        action: () => {
                            actions.restoreDashboard({ id: dashboard.id, redirect: values.redirect })
                        },
                    },
                }
            )

            actions.delayedDeleteDashboard(dashboard.id)
        },

        duplicateDashboardSuccess: async ({ dashboard }) => {
            lemonToast.success(
                <>
                    Dashboard copied as <b>{dashboard.name}</b>
                </>
            )
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDashboards()
    }),
    permanentlyMount(),
])

export function nameCompareFunction(a: DashboardBasicType, b: DashboardBasicType): number {
    if (a.pinned !== b.pinned) {
        return b.pinned ? 1 : -1
    }

    // No matter where we're comparing dashboards, we want to sort generated dashboards last
    const firstName = a.name ?? 'Untitled'
    const secondName = b.name ?? 'Untitled'

    return firstName.localeCompare(secondName)
}

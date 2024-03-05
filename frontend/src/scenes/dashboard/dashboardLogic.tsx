import {
    actions,
    connect,
    events,
    isBreakpoint,
    kea,
    key,
    listeners,
    path,
    props,
    reducers,
    selectors,
    sharedListeners,
} from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { ApiMethodOptions, getJSONOrThrow } from 'lib/api'
import {
    AUTO_REFRESH_DASHBOARD_THRESHOLD_HOURS,
    DashboardPrivilegeLevel,
    OrganizationMembershipLevel,
} from 'lib/constants'
import { Dayjs, dayjs, now } from 'lib/dayjs'
import { captureTimeToSeeData, currentSessionId, TimeToSeeDataPayload } from 'lib/internalMetrics'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { clearDOMTextSelection, isUserLoggedIn, shouldCancelQuery, toParams, uuid } from 'lib/utils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Layout, Layouts } from 'react-grid-layout'
import { calculateLayouts } from 'scenes/dashboard/tileLayouts'
import { insightLogic } from 'scenes/insights/insightLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import {
    AnyPropertyFilter,
    Breadcrumb,
    DashboardLayoutSize,
    DashboardMode,
    DashboardPlacement,
    DashboardTemplateEditorType,
    DashboardTile,
    DashboardType,
    FilterType,
    InsightColor,
    InsightModel,
    InsightShortId,
    TextModel,
    TileLayout,
} from '~/types'

import { getResponseBytes, sortDates, sortDayJsDates } from '../insights/utils'
import { teamLogic } from '../teamLogic'
import type { dashboardLogicType } from './dashboardLogicType'

export const BREAKPOINTS: Record<DashboardLayoutSize, number> = {
    sm: 1024,
    xs: 0,
}
export const BREAKPOINT_COLUMN_COUNTS: Record<DashboardLayoutSize, number> = { sm: 12, xs: 1 }

export const DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES = 5

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export interface DashboardLogicProps {
    id: number
    dashboard?: DashboardType
    placement?: DashboardPlacement
}

export interface RefreshStatus {
    /** Insight is about to be loaded */
    queued?: boolean
    /** Insight is currently loading */
    loading?: boolean
    refreshed?: boolean
    error?: boolean
    timer?: Date | null
}

export const AUTO_REFRESH_INITIAL_INTERVAL_SECONDS = 1800

// to stop kea typegen getting confused
export type DashboardTileLayoutUpdatePayload = Pick<DashboardTile, 'id' | 'layouts'>

const layoutsByTile = (layouts: Layouts): Record<number, Record<DashboardLayoutSize, TileLayout>> => {
    const itemLayouts: Record<number, Record<DashboardLayoutSize, TileLayout>> = {}

    Object.entries(layouts).forEach(([col, layout]) => {
        layout.forEach((layoutItem) => {
            if (!itemLayouts[layoutItem.i]) {
                itemLayouts[layoutItem.i] = {}
            }
            itemLayouts[layoutItem.i][col] = layoutItem
        })
    })
    return itemLayouts
}

interface InsightCacheReloadProps {
    cachedInsight: InsightModel
    dashboardId: number
    refreshedInsight: InsightModel
}

/**
 * :TRICKY: Changes in dashboards don't automatically propagate to already mounted insights!
 * This function updates insightLogics individually.
 *
 * Call this whenever updating already rendered tiles within dashboardLogic
 */
function updateExistingInsightState({ cachedInsight, dashboardId, refreshedInsight }: InsightCacheReloadProps): void {
    if (refreshedInsight.filters.insight) {
        const itemResultLogic = insightLogic.findMounted({
            dashboardItemId: refreshedInsight.short_id,
            dashboardId: dashboardId,
            cachedInsight: cachedInsight,
        })
        itemResultLogic?.actions.setInsight(refreshedInsight, { fromPersistentApi: true })
    }
}

export const dashboardLogic = kea<dashboardLogicType>([
    path(['scenes', 'dashboard', 'dashboardLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
        logic: [dashboardsModel, insightsModel, eventUsageLogic],
    })),

    props({} as DashboardLogicProps),

    key((props) => {
        if (typeof props.id !== 'number') {
            throw Error('Must init dashboardLogic with a numeric ID key')
        }
        return props.id
    }),

    actions({
        loadDashboardItems: (payload: { refresh?: boolean; action: string }) => payload,
        triggerDashboardUpdate: (payload) => ({ payload }),
        /** The current state in which the dashboard is being viewed, see DashboardMode. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource | null) => ({ mode, source }),
        saveLayouts: (tilesToSave: DashboardTileLayoutUpdatePayload[] = []) => ({ tilesToSave }),
        updateLayouts: (layouts: Layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        updateTileColor: (tileId: number, color: string | null) => ({ tileId, color }),
        removeTile: (tile: DashboardTile) => ({ tile }),
        refreshAllDashboardItems: (payload: {
            tiles?: DashboardTile[]
            action: string
            initialLoad?: boolean
            dashboardQueryId?: string
        }) => payload,
        refreshAllDashboardItemsManual: true,
        resetInterval: true,
        updateAndRefreshDashboard: true,
        setDates: (dateFrom: string | null, dateTo: string | null) => ({
            dateFrom,
            dateTo,
        }),
        setProperties: (properties: AnyPropertyFilter[]) => ({ properties }),
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        setRefreshStatus: (shortId: InsightShortId, loading = false, queued = false) => ({ shortId, loading, queued }),
        setRefreshStatuses: (shortIds: InsightShortId[], loading = false, queued = false) => ({
            shortIds,
            loading,
            queued,
        }),
        setRefreshError: (shortId: InsightShortId) => ({ shortId }),
        reportDashboardViewed: true, // Reports `viewed dashboard` and `dashboard analyzed` events
        setShouldReportOnAPILoad: (shouldReport: boolean) => ({ shouldReport }), // See reducer for details
        setSubscriptionMode: (enabled: boolean, id?: number | 'new') => ({ enabled, id }),
        moveToDashboard: (
            tile: DashboardTile,
            fromDashboard: number,
            toDashboard: number,
            toDashboardName: string,
            allowUndo?: boolean
        ) => ({
            tile,
            fromDashboard,
            toDashboard,
            toDashboardName,
            allowUndo: allowUndo === undefined ? true : allowUndo,
        }),
        setTextTileId: (textTileId: number | 'new' | null) => ({ textTileId }),
        duplicateTile: (tile: DashboardTile) => ({ tile }),
        loadingDashboardItemsStarted: (action: string, dashboardQueryId: string) => ({ action, dashboardQueryId }),
        setInitialLoadResponseBytes: (responseBytes: number) => ({ responseBytes }),
        abortQuery: (payload: { dashboardQueryId: string; queryId: string; queryStartTime: number }) => payload,
        abortAnyRunningQuery: true,
    }),

    loaders(({ actions, props, values }) => ({
        dashboard: [
            null as DashboardType | null,
            {
                loadDashboardItems: async ({ refresh, action }) => {
                    const dashboardQueryId = uuid()
                    actions.loadingDashboardItemsStarted(action, dashboardQueryId)

                    try {
                        // :TODO: Send dashboardQueryId forward as well if refreshing
                        const apiUrl = values.apiUrl(refresh)
                        const dashboardResponse: Response = await api.getResponse(apiUrl)
                        const dashboard: DashboardType = await getJSONOrThrow(dashboardResponse)

                        actions.setInitialLoadResponseBytes(getResponseBytes(dashboardResponse))

                        return dashboard
                    } catch (error: any) {
                        if (error.status === 404) {
                            throw new Error('Dashboard not found')
                        }
                        throw error
                    }
                },
                updateFilters: async () => {
                    actions.abortAnyRunningQuery()

                    try {
                        return await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                            filters: values.filters,
                        })
                    } catch (e) {
                        lemonToast.error('Could not update dashboardFilters: ' + String(e))
                        return values.dashboard
                    }
                },
                updateTileColor: async ({ tileId, color }) => {
                    await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                        tiles: [{ id: tileId, color }],
                    })
                    const matchingTile = values.tiles.find((tile) => tile.id === tileId)
                    if (matchingTile) {
                        matchingTile.color = color as InsightColor
                    }
                    return values.dashboard
                },
                removeTile: async ({ tile }) => {
                    try {
                        await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                            tiles: [{ id: tile.id, deleted: true }],
                        })
                        dashboardsModel.actions.tileRemovedFromDashboard({
                            tile: tile,
                            dashboardId: props.id,
                        })

                        return {
                            ...values.dashboard,
                            tiles: values.tiles.filter((t) => t.id !== tile.id),
                        } as DashboardType
                    } catch (e) {
                        lemonToast.error('Could not remove tile from dashboard: ' + String(e))
                        return values.dashboard
                    }
                },
                duplicateTile: async ({ tile }) => {
                    try {
                        const newTile = { ...tile } as Partial<DashboardTile>
                        delete newTile.id
                        if (newTile.text) {
                            newTile.text = { body: newTile.text.body } as TextModel
                        }
                        return await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                            tiles: [newTile],
                        } as Partial<InsightModel>)
                    } catch (e) {
                        lemonToast.error('Could not duplicate tile: ' + String(e))
                        return values.dashboard
                    }
                },
                moveToDashboard: async ({ tile, fromDashboard, toDashboard }) => {
                    if (!tile || fromDashboard === toDashboard) {
                        return values.dashboard
                    }

                    if (fromDashboard !== props.id) {
                        return values.dashboard
                    } else {
                        return await api.update(
                            `api/projects/${teamLogic.values.currentTeamId}/dashboards/${props.id}/move_tile`,
                            {
                                tile,
                                toDashboard,
                            }
                        )
                    }
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        receivedErrorsFromAPI: [
            false,
            {
                loadDashboardItemsSuccess: () => false,
                loadDashboardItemsFailure: () => true,
                abortQuery: () => false,
            },
        ],
        filters: [
            { date_from: null, date_to: null, properties: [] } as FilterType,
            {
                setDates: (state, { dateFrom, dateTo }) => ({
                    ...state,
                    date_from: dateFrom || null,
                    date_to: dateTo || null,
                }),
                setProperties: (state, { properties }) => ({
                    ...state,
                    properties: properties || null,
                }),
                loadDashboardItemsSuccess: (state, { dashboard }) => ({
                    ...state,
                    date_from: dashboard?.filters.date_from || null,
                    date_to: dashboard?.filters.date_to || null,
                    properties: dashboard?.filters.properties || [],
                }),
            },
        ],
        dashboard: [
            null as DashboardType | null,
            {
                updateLayouts: (state, { layouts }) => {
                    const itemLayouts = layoutsByTile(layouts)

                    return {
                        ...state,
                        tiles: state?.tiles?.map((tile) => ({ ...tile, layouts: itemLayouts[tile.id] })),
                    } as DashboardType
                },
                [dashboardsModel.actionTypes.tileMovedToDashboard]: (state, { tile, dashboardId }) => {
                    if (state?.id === dashboardId) {
                        return {
                            ...state,
                            tiles: [...state.tiles, tile],
                        }
                    }
                    return state
                },
                [dashboardsModel.actionTypes.updateDashboardInsight]: (
                    state,
                    { insight, extraDashboardIds, updateTileOnDashboards }
                ) => {
                    const targetDashboards = (insight.dashboards || []).concat(extraDashboardIds || [])
                    if (!targetDashboards.includes(props.id)) {
                        // this update is not for this dashboard
                        return state
                    }

                    if (state) {
                        const tileIndex = state.tiles.findIndex(
                            (t) => !!t.insight && t.insight.short_id === insight.short_id
                        )

                        const newTiles = state.tiles.slice(0)

                        if (tileIndex >= 0) {
                            if (insight.dashboards?.includes(props.id)) {
                                newTiles[tileIndex] = { ...newTiles[tileIndex], insight: insight }
                                if (updateTileOnDashboards?.includes(props.id)) {
                                    newTiles[tileIndex].last_refresh = insight.last_refresh
                                }
                            } else {
                                newTiles.splice(tileIndex, 1)
                            }
                        } else {
                            // we can't create tiles in this reducer
                            // will reload all items in a listener to pick up the new tile
                        }

                        return {
                            ...state,
                            tiles: newTiles.filter((t) => !t.deleted || !t.insight?.deleted),
                        } as DashboardType
                    }

                    return null
                },
                [dashboardsModel.actionTypes.updateDashboardSuccess]: (state, { dashboard }) => {
                    return state && dashboard && state.id === dashboard.id ? dashboard : state
                },
                [dashboardsModel.actionTypes.updateDashboardRefreshStatus]: (
                    state,
                    { shortId, refreshing, last_refresh }
                ) => {
                    // If not a dashboard item, don't do anything.
                    if (!shortId) {
                        return state
                    }
                    return {
                        ...state,
                        items: state?.tiles.map((t) =>
                            !t.insight || t.insight.short_id === shortId
                                ? {
                                      ...t,
                                      ...(refreshing != null ? { refreshing } : {}),
                                      ...(last_refresh != null ? { last_refresh } : {}),
                                  }
                                : t
                        ),
                    } as DashboardType
                },
                [insightsModel.actionTypes.renameInsightSuccess]: (state, { item }): DashboardType | null => {
                    const tileIndex = state?.tiles.findIndex((t) => !!t.insight && t.insight.short_id === item.short_id)
                    const tiles = state?.tiles.slice(0)

                    if (tileIndex === undefined || tileIndex === -1 || !tiles) {
                        return state
                    }

                    tiles[tileIndex] = {
                        ...tiles[tileIndex],
                        insight: {
                            ...(tiles[tileIndex].insight as InsightModel),
                            name: item.name,
                            last_modified_at: item.last_modified_at,
                        },
                    }

                    return {
                        ...state,
                        tiles,
                    } as DashboardType
                },
            },
        ],
        loadTimer: [null as Date | null, { loadDashboardItems: () => new Date() }],
        dashboardLoadTimerData: [
            { dashboardQueryId: '', action: '', startTime: 0, responseBytes: 0 },
            {
                loadingDashboardItemsStarted: (_, { action, dashboardQueryId }) => ({
                    action,
                    dashboardQueryId,
                    startTime: performance.now(),
                    responseBytes: 0,
                }),
                setInitialLoadResponseBytes: (state, { responseBytes }) => ({
                    ...state,
                    responseBytes,
                }),
            },
        ],
        refreshStatus: [
            {} as Record<string, RefreshStatus>,
            {
                setRefreshStatus: (state, { shortId, loading, queued }) => ({
                    ...state,
                    [shortId]: loading
                        ? { loading: true, queued: true, timer: new Date() }
                        : queued
                        ? { loading: false, queued: true, timer: null }
                        : { refreshed: true, timer: state[shortId]?.timer || null },
                }),
                setRefreshStatuses: (state, { shortIds, loading, queued }) =>
                    Object.fromEntries(
                        shortIds.map((shortId) => [
                            shortId,
                            loading
                                ? { loading: true, queued: true, timer: new Date() }
                                : queued
                                ? { loading: false, queued: true, timer: null }
                                : { refreshed: true, timer: state[shortId]?.timer || null },
                        ])
                    ) as Record<string, RefreshStatus>,
                setRefreshError: (state, { shortId }) => ({
                    ...state,
                    [shortId]: { error: true, timer: state[shortId]?.timer || null },
                }),
                refreshAllDashboardItems: () => ({}),
                abortQuery: () => ({}),
            },
        ],
        columns: [
            null as number | null,
            {
                updateContainerWidth: (_, { columns }) => columns,
            },
        ],
        containerWidth: [
            null as number | null,
            {
                updateContainerWidth: (_, { containerWidth }) => containerWidth,
            },
        ],
        dashboardMode: [
            null as DashboardMode | null,
            {
                setDashboardMode: (_, { mode }) => mode,
            },
        ],
        lastDashboardModeSource: [
            null as DashboardEventSource | null,
            {
                setDashboardMode: (_, { source }) => source,
            },
        ],
        autoRefresh: [
            {
                interval: AUTO_REFRESH_INITIAL_INTERVAL_SECONDS,
                enabled: false,
            } as {
                interval: number
                enabled: boolean
            },
            { persist: true, prefix: '2_' },
            {
                setAutoRefresh: (_, { enabled, interval }) => ({ enabled, interval }),
            },
        ],
        shouldReportOnAPILoad: [
            /* Whether to report viewed/analyzed events after the API is loaded (and this logic is mounted).
            We need this because the DashboardView component might be mounted (and subsequent `useEffect`) before the API request
            to `loadDashboardItems` is completed (e.g. if you open PH directly to a dashboard)
            */
            false,
            {
                setShouldReportOnAPILoad: (_, { shouldReport }) => shouldReport,
            },
        ],

        showSubscriptions: [
            false,
            {
                setSubscriptionMode: (_, { enabled }) => enabled,
            },
        ],
        subscriptionId: [
            null as number | 'new' | null,
            {
                setSubscriptionMode: (_, { id }) => id || null,
            },
        ],

        showTextTileModal: [
            false,
            {
                setTextTileId: (_, { textTileId }) => !!textTileId,
            },
        ],
        textTileId: [
            null as number | 'new' | null,
            {
                setTextTileId: (_, { textTileId }) => textTileId,
            },
        ],
    })),
    selectors(() => ({
        asDashboardTemplate: [
            (s) => [s.dashboard],
            (dashboard: DashboardType): DashboardTemplateEditorType | undefined => {
                return dashboard
                    ? {
                          template_name: dashboard.name,
                          dashboard_description: dashboard.description,
                          dashboard_filters: dashboard.filters,
                          tags: dashboard.tags || [],
                          tiles: dashboard.tiles.map((tile) => {
                              if (tile.text) {
                                  return {
                                      type: 'TEXT',
                                      body: tile.text.body,
                                      layouts: tile.layouts,
                                      color: tile.color,
                                  }
                              }
                              if (tile.insight) {
                                  return {
                                      type: 'INSIGHT',
                                      name: tile.insight.name,
                                      description: tile.insight.description || '',
                                      filters: tile.insight.filters,
                                      query: tile.insight.query,
                                      layouts: tile.layouts,
                                      color: tile.color,
                                  }
                              }
                              throw new Error('Unknown tile type')
                          }),
                          variables: [],
                      }
                    : undefined
            },
        ],
        placement: [
            () => [(_, props) => props.placement],
            (placement): DashboardPlacement => placement || DashboardPlacement.Dashboard,
        ],
        apiUrl: [
            () => [(_, props) => props.id],
            (id) => {
                return (refresh?: boolean) =>
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}/?${toParams({
                        refresh,
                    })}`
            },
        ],
        tiles: [(s) => [s.dashboard], (dashboard) => dashboard?.tiles?.filter((t) => !t.deleted) || []],
        insightTiles: [
            (s) => [s.tiles],
            (tiles) => tiles.filter((t) => !!t.insight).filter((i) => !i.insight?.deleted),
        ],
        textTiles: [(s) => [s.tiles], (tiles) => tiles.filter((t) => !!t.text)],
        itemsLoading: [
            (s) => [s.dashboardLoading, s.refreshStatus],
            (dashboardLoading, refreshStatus) => {
                return dashboardLoading || Object.values(refreshStatus).some((s) => s.loading)
            },
        ],
        isRefreshingQueued: [(s) => [s.refreshStatus], (refreshStatus) => (id: string) => !!refreshStatus[id]?.queued],
        isRefreshing: [(s) => [s.refreshStatus], (refreshStatus) => (id: string) => !!refreshStatus[id]?.loading],
        highlightedInsightId: [
            () => [router.selectors.searchParams],
            (searchParams) => searchParams.highlightInsightId,
        ],
        lastRefreshed: [
            (s) => [s.insightTiles],
            (insightTiles): Dayjs | null => {
                if (!insightTiles || !insightTiles.length) {
                    return null
                }

                const validDates = insightTiles.map((i) => dayjs(i.last_refresh)).filter((date) => date.isValid())
                const oldest = sortDayJsDates(validDates)
                return oldest.length > 0 ? oldest[0] : null
            },
        ],
        blockRefresh: [
            (s) => [s.lastRefreshed, s.placement],
            (lastRefreshed: Dayjs, placement: DashboardPlacement) => {
                return (
                    !!lastRefreshed &&
                    !(placement === DashboardPlacement.FeatureFlag) &&
                    now()
                        .subtract(DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES - 0.5, 'minutes')
                        .isBefore(lastRefreshed)
                )
            },
        ],
        canEditDashboard: [
            (s) => [s.dashboard],
            (dashboard) => !!dashboard && dashboard.effective_privilege_level >= DashboardPrivilegeLevel.CanEdit,
        ],
        canRestrictDashboard: [
            // Sync conditions with backend can_user_restrict
            (s) => [s.dashboard, userLogic.selectors.user, teamLogic.selectors.currentTeam],
            (dashboard, user, currentTeam): boolean =>
                !!dashboard &&
                !!user &&
                (user.uuid === dashboard.created_by?.uuid ||
                    (!!currentTeam?.effective_membership_level &&
                        currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin)),
        ],
        sizeKey: [
            (s) => [s.columns],
            (columns): DashboardLayoutSize | undefined => {
                const [size] = (Object.entries(BREAKPOINT_COLUMN_COUNTS).find(([, value]) => value === columns) ||
                    []) as [DashboardLayoutSize, number]
                return size
            },
        ],
        layouts: [(s) => [s.tiles], (tiles) => calculateLayouts(tiles)],
        layout: [(s) => [s.layouts, s.sizeKey], (layouts, sizeKey) => (sizeKey ? layouts[sizeKey] : undefined)],
        layoutForItem: [
            (s) => [s.layout],
            (layout) => {
                const layoutForItem: Record<string, Layout> = {}
                if (layout) {
                    for (const obj of layout) {
                        layoutForItem[obj.i] = obj
                    }
                }
                return layoutForItem
            },
        ],
        refreshMetrics: [
            (s) => [s.refreshStatus],
            (refreshStatus) => {
                const total = Object.keys(refreshStatus).length ?? 0
                return {
                    completed: total - (Object.values(refreshStatus).filter((s) => s.loading || s.queued).length ?? 0),
                    total,
                }
            },
        ],
        breadcrumbs: [
            (s) => [s.dashboard],
            (dashboard): Breadcrumb[] => [
                {
                    key: Scene.Dashboards,
                    name: 'Dashboards',
                    path: urls.dashboards(),
                },
                {
                    key: [Scene.Dashboard, dashboard?.id || 'new'],
                    name: dashboard?.id ? dashboard.name || 'Unnamed' : null,
                    onRename: async (name) => {
                        if (dashboard) {
                            await dashboardsModel.asyncActions.updateDashboard({
                                id: dashboard.id,
                                name,
                                allowUndo: true,
                            })
                        }
                    },
                },
            ],
        ],
        sortTilesByLayout: [
            (s) => [s.layoutForItem],
            (layoutForItem) => (tiles: Array<DashboardTile>) => {
                return [...tiles].sort((a: DashboardTile, b: DashboardTile) => {
                    const ax = layoutForItem[a.id]?.x ?? 0
                    const ay = layoutForItem[a.id]?.y ?? 0
                    const bx = layoutForItem[b.id]?.x ?? 0
                    const by = layoutForItem[b.id]?.y ?? 0
                    if (ay < by || (ay == by && ax < bx)) {
                        return -1
                    } else if (ay > by || (ay == by && ax > bx)) {
                        return 1
                    } else {
                        return 0
                    }
                })
            },
        ],
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadDashboardItems({
                refresh: false,
                action: 'initial_load',
            })
        },
        beforeUnmount: () => {
            if (cache.autoRefreshInterval) {
                window.clearInterval(cache.autoRefreshInterval)
                cache.autoRefreshInterval = null
            }
        },
    })),
    sharedListeners(({ values, props }) => ({
        reportRefreshTiming: ({ shortId }) => {
            const refreshStatus = values.refreshStatus[shortId]

            if (refreshStatus?.timer) {
                const loadingMilliseconds = new Date().getTime() - refreshStatus.timer.getTime()
                eventUsageLogic.actions.reportInsightRefreshTime(loadingMilliseconds, shortId)
            }
        },
        reportLoadTiming: () => {
            if (values.loadTimer) {
                const loadingMilliseconds = new Date().getTime() - values.loadTimer.getTime()
                eventUsageLogic.actions.reportDashboardLoadingTime(loadingMilliseconds, props.id)
            }
        },
    })),
    listeners(({ actions, values, cache, props, sharedListeners }) => ({
        updateFiltersSuccess: () => {
            actions.refreshAllDashboardItems({ action: 'refresh_insights_on_filters_updated' })
        },
        setRefreshError: sharedListeners.reportRefreshTiming,
        setRefreshStatuses: sharedListeners.reportRefreshTiming,
        setRefreshStatus: sharedListeners.reportRefreshTiming,
        loadDashboardItemsFailure: sharedListeners.reportLoadTiming,
        [insightsModel.actionTypes.duplicateInsightSuccess]: () => {
            // TODO this is a bit hacky, but we need to reload the dashboard to get the new insight
            // TODO when duplicated from a dashboard we should carry the context so only one logic needs to reload
            // TODO or we should duplicate the tile (and implicitly the insight)
            actions.loadDashboardItems({ action: 'update' })
        },
        [dashboardsModel.actionTypes.tileAddedToDashboard]: ({ dashboardId }) => {
            // when adding an insight to a dashboard, we need to reload the dashboard to get the new insight
            if (dashboardId === props.id) {
                actions.loadDashboardItems({ action: 'update' })
            }
        },
        [dashboardsModel.actionTypes.updateDashboardInsight]: ({ insight, extraDashboardIds }) => {
            const targetDashboards = (insight.dashboards || []).concat(extraDashboardIds || [])
            if (!targetDashboards.includes(props.id)) {
                // this update is not for this dashboard
                return
            }

            const tileIndex = values.tiles.findIndex((t) => !!t.insight && t.insight.short_id === insight.short_id)

            if (tileIndex === -1) {
                // this is a new tile created from an insight context we need to reload the dashboard
                actions.loadDashboardItems({ action: 'update' })
            }
        },
        updateLayouts: () => {
            actions.saveLayouts()
        },
        saveLayouts: async ({ tilesToSave }, breakpoint) => {
            await breakpoint(300)
            if (!isUserLoggedIn()) {
                // If user is anonymous (i.e. viewing a shared dashboard logged out), we don't save any layout changes.
                return
            }
            const layoutsToUpdate = tilesToSave.length
                ? tilesToSave
                : (values.dashboard?.tiles || []).map((tile) => ({ id: tile.id, layouts: tile.layouts }))

            breakpoint()

            return await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                tiles: layoutsToUpdate,
            })
        },
        moveToDashboardSuccess: ({ payload }) => {
            if (payload?.toDashboard === undefined || payload?.tile === undefined) {
                return
            }

            const updatedTile = { ...payload.tile }
            if (updatedTile.insight !== undefined && updatedTile.insight !== null) {
                updatedTile.insight.dashboards =
                    payload.tile.insight?.dashboards?.filter((d) => d !== payload.fromDashboard) || []
                updatedTile.insight.dashboards.push(payload.toDashboard)
            }
            if (updatedTile) {
                dashboardsModel.actions.tileMovedToDashboard(updatedTile, payload.toDashboard)

                lemonToast.success(
                    <>
                        Insight moved to{' '}
                        <b>
                            <Link to={urls.dashboard(payload?.toDashboard)}>{payload?.toDashboardName}</Link>
                        </b>
                    </>
                    // TODO implement undo for move to dashboard
                )
            }
        },
        triggerDashboardUpdate: ({ payload }) => {
            if (values.dashboard) {
                dashboardsModel.actions.updateDashboard({ id: values.dashboard.id, ...payload })
            }
        },
        refreshAllDashboardItemsManual: () => {
            // reset auto refresh interval
            actions.resetInterval()
            actions.refreshAllDashboardItems({ action: 'refresh' })
        },
        refreshAllDashboardItems: async ({ tiles, action, initialLoad, dashboardQueryId = uuid() }, breakpoint) => {
            const dashboardId: number = props.id

            const insights = values
                .sortTilesByLayout(tiles || values.insightTiles || [])
                .map((t) => t.insight)
                .filter((i): i is InsightModel => !!i)

            // Don't do anything if there's nothing to refresh
            if (insights.length === 0) {
                return
            }

            let cancelled = false
            actions.setRefreshStatuses(
                insights.map((item) => item.short_id),
                false,
                true
            )

            // we will use one abort controller for all insight queries for this dashboard
            actions.abortAnyRunningQuery()
            cache.abortController = new AbortController()
            const methodOptions: ApiMethodOptions = {
                signal: cache.abortController.signal,
            }

            const refreshStartTime = performance.now()

            let refreshesFinished = 0
            let totalResponseBytes = 0

            const hardRefreshWithoutCache = ['refresh', 'load_missing'].includes(action)

            // array of functions that reload each item
            const fetchItemFunctions = insights.map((insight) => async () => {
                // :TODO: Support query cancellation and use this queryId in the actual query.
                // :TODO: in the future we should use dataNodeCollectionLogic.reloadAll()
                const queryId = `${dashboardQueryId}::${uuid()}`
                const queryStartTime = performance.now()
                const apiUrl = `api/projects/${values.currentTeamId}/insights/${insight.id}/?${toParams({
                    refresh: hardRefreshWithoutCache,
                    from_dashboard: dashboardId, // needed to load insight in correct context
                    client_query_id: queryId,
                    session_id: currentSessionId(),
                })}`

                actions.setRefreshStatus(insight.short_id, true, true)

                try {
                    breakpoint()

                    const refreshedInsightResponse: Response = await api.getResponse(apiUrl, methodOptions)
                    const refreshedInsight: InsightModel = await getJSONOrThrow(refreshedInsightResponse)
                    breakpoint()
                    updateExistingInsightState({ cachedInsight: insight, dashboardId, refreshedInsight })
                    dashboardsModel.actions.updateDashboardInsight(
                        refreshedInsight,
                        [],
                        props.id ? [props.id] : undefined
                    )
                    actions.setRefreshStatus(insight.short_id)

                    void captureTimeToSeeData(values.currentTeamId, {
                        type: 'insight_load',
                        context: 'dashboard',
                        primary_interaction_id: dashboardQueryId,
                        query_id: queryId,
                        status: 'success',
                        time_to_see_data_ms: Math.floor(performance.now() - queryStartTime),
                        api_response_bytes: getResponseBytes(refreshedInsightResponse),
                        insights_fetched: 1,
                        insights_fetched_cached: 0,
                        api_url: apiUrl,
                    })
                    totalResponseBytes += getResponseBytes(refreshedInsightResponse)
                } catch (e: any) {
                    if (isBreakpoint(e)) {
                        cancelled = true
                    } else if (shouldCancelQuery(e)) {
                        if (!cancelled) {
                            // cancel all insight requests for this query in one go
                            actions.abortQuery({ dashboardQueryId: dashboardQueryId, queryId: queryId, queryStartTime })
                        }
                        cancelled = true
                    } else {
                        actions.setRefreshError(insight.short_id)
                    }
                }

                refreshesFinished += 1
                if (!cancelled && refreshesFinished === insights.length) {
                    const payload: TimeToSeeDataPayload = {
                        type: 'dashboard_load',
                        context: 'dashboard',
                        action,
                        primary_interaction_id: dashboardQueryId,
                        api_response_bytes: totalResponseBytes,
                        time_to_see_data_ms: Math.floor(performance.now() - refreshStartTime),
                        insights_fetched: insights.length,
                        insights_fetched_cached: 0,
                    }
                    void captureTimeToSeeData(values.currentTeamId, {
                        ...payload,
                        is_primary_interaction: !initialLoad,
                    })
                    if (initialLoad) {
                        const { startTime, responseBytes } = values.dashboardLoadTimerData
                        void captureTimeToSeeData(values.currentTeamId, {
                            ...payload,
                            action: 'initial_load_full',
                            time_to_see_data_ms: Math.floor(performance.now() - startTime),
                            api_response_bytes: responseBytes + totalResponseBytes,
                            is_primary_interaction: true,
                        })
                    }
                }
            })

            async function loadNextPromise(): Promise<void> {
                if (!cancelled && fetchItemFunctions.length > 0) {
                    const nextPromise = fetchItemFunctions.shift()
                    if (nextPromise) {
                        await nextPromise()
                        await loadNextPromise()
                    }
                }
            }

            void loadNextPromise()

            eventUsageLogic.actions.reportDashboardRefreshed(dashboardId, values.lastRefreshed)
        },
        setDates: ({ dateFrom, dateTo }) => {
            actions.updateFilters()
            eventUsageLogic.actions.reportDashboardDateRangeChanged(dateFrom, dateTo)
        },
        setProperties: () => {
            actions.updateFilters()
            eventUsageLogic.actions.reportDashboardPropertiesChanged()
        },
        setDashboardMode: async ({ mode, source }) => {
            if (mode === DashboardMode.Edit) {
                clearDOMTextSelection()
            }

            if (mode) {
                eventUsageLogic.actions.reportDashboardModeToggled(mode, source)
            }
        },
        setAutoRefresh: () => {
            actions.resetInterval()
        },
        resetInterval: () => {
            if (cache.autoRefreshInterval) {
                window.clearInterval(cache.autoRefreshInterval)
                cache.autoRefreshInterval = null
            }

            if (values.autoRefresh.enabled) {
                // Refresh right now after enabling if we haven't refreshed recently
                if (
                    !values.itemsLoading &&
                    values.lastRefreshed &&
                    values.lastRefreshed.isBefore(now().subtract(values.autoRefresh.interval, 'seconds'))
                ) {
                    actions.refreshAllDashboardItems({ action: 'refresh' })
                }
                cache.autoRefreshInterval = window.setInterval(() => {
                    actions.refreshAllDashboardItems({ action: 'refresh' })
                }, values.autoRefresh.interval * 1000)
            }
        },
        loadDashboardItemsSuccess: function (...args) {
            void sharedListeners.reportLoadTiming(...args)

            const dashboard = values.dashboard as DashboardType
            const { action, dashboardQueryId, startTime, responseBytes } = values.dashboardLoadTimerData
            const lastRefresh = sortDates(dashboard.tiles.map((tile) => tile.last_refresh))

            const initialLoad = action === 'initial_load'
            let allLoaded = true

            // Initial load of actual data for dashboard items after general dashboard is fetched
            if (
                values.lastRefreshed &&
                values.lastRefreshed.isBefore(now().subtract(AUTO_REFRESH_DASHBOARD_THRESHOLD_HOURS, 'hours')) &&
                !process.env.STORYBOOK // allow mocking of date in storybook without triggering refresh
            ) {
                actions.refreshAllDashboardItems({ action: 'refresh', initialLoad, dashboardQueryId })
                allLoaded = false
            } else {
                const tilesWithNoResults = values.tiles?.filter((t) => !!t.insight && !t.insight.result) || []
                const tilesWithResults = values.tiles?.filter((t) => !!t.insight && t.insight.result) || []

                if (tilesWithNoResults.length) {
                    actions.refreshAllDashboardItems({
                        tiles: tilesWithNoResults,
                        action: 'load_missing',
                        initialLoad,
                        dashboardQueryId,
                    })
                    allLoaded = false
                }

                for (const tile of tilesWithResults) {
                    if (tile.insight) {
                        updateExistingInsightState({
                            cachedInsight: tile.insight,
                            dashboardId: dashboard.id,
                            refreshedInsight: tile.insight,
                        })
                        dashboardsModel.actions.updateDashboardInsight(tile.insight)
                    }
                }
            }

            const payload: TimeToSeeDataPayload = {
                type: 'dashboard_load',
                context: 'dashboard',
                action,
                primary_interaction_id: dashboardQueryId,
                time_to_see_data_ms: Math.floor(performance.now() - startTime),
                api_response_bytes: responseBytes,
                insights_fetched: dashboard.tiles.length,
                insights_fetched_cached: dashboard.tiles.reduce((acc, curr) => acc + (curr.is_cached ? 1 : 0), 0),
                min_last_refresh: lastRefresh[0],
                max_last_refresh: lastRefresh[lastRefresh.length - 1],
                is_primary_interaction: !initialLoad,
            }

            void captureTimeToSeeData(values.currentTeamId, payload)
            if (initialLoad && allLoaded) {
                void captureTimeToSeeData(values.currentTeamId, {
                    ...payload,
                    action: 'initial_load_full',
                    is_primary_interaction: true,
                })
            }

            if (values.shouldReportOnAPILoad) {
                actions.setShouldReportOnAPILoad(false)
                actions.reportDashboardViewed()
            }
        },
        reportDashboardViewed: async (_, breakpoint) => {
            // Caching `dashboard`, as the dashboard might have unmounted after the breakpoint,
            // and "values.dashboard" will then fail
            const { dashboard, lastRefreshed } = values
            if (dashboard) {
                eventUsageLogic.actions.reportDashboardViewed(dashboard, lastRefreshed)
                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish
                if (
                    router.values.location.pathname === urls.dashboard(dashboard.id) ||
                    router.values.location.pathname === urls.projectHomepage() ||
                    router.values.location.pathname.startsWith(urls.sharedDashboard(''))
                ) {
                    eventUsageLogic.actions.reportDashboardViewed(dashboard, lastRefreshed, 10)
                }
            } else {
                // dashboard has not loaded yet, report after API request is completed
                actions.setShouldReportOnAPILoad(true)
            }
        },
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        abortQuery: async ({ dashboardQueryId, queryId, queryStartTime }) => {
            const { currentTeamId } = values

            await api.create(`api/projects/${currentTeamId}/insights/cancel`, { client_query_id: dashboardQueryId })

            // TRICKY: we cancel just once using the dashboard query id.
            // we can record the queryId that happened to capture the AbortError exception
            // and request the cancellation, but it is probably not particularly relevant
            await captureTimeToSeeData(values.currentTeamId, {
                type: 'insight_load',
                context: 'dashboard',
                primary_interaction_id: dashboardQueryId,
                query_id: queryId,
                status: 'cancelled',
                time_to_see_data_ms: Math.floor(performance.now() - queryStartTime),
                insights_fetched: 0,
                insights_fetched_cached: 0,
            })
        },
    })),

    urlToAction(({ actions }) => ({
        '/dashboard/:id/subscriptions(/:subscriptionId)': ({ subscriptionId }) => {
            const id = subscriptionId
                ? subscriptionId == 'new'
                    ? subscriptionId
                    : parseInt(subscriptionId, 10)
                : undefined
            actions.setSubscriptionMode(true, id)
            actions.setTextTileId(null)
            actions.setDashboardMode(null, null)
        },

        '/dashboard/:id': () => {
            actions.setSubscriptionMode(false, undefined)
            actions.setTextTileId(null)
            actions.setDashboardMode(null, DashboardEventSource.Browser)
        },
        '/dashboard/:id/sharing': () => {
            actions.setSubscriptionMode(false, undefined)
            actions.setTextTileId(null)
            actions.setDashboardMode(DashboardMode.Sharing, null)
        },
        '/dashboard/:id/text-tiles/:textTileId': ({ textTileId }) => {
            actions.setSubscriptionMode(false, undefined)
            actions.setDashboardMode(null, null)
            actions.setTextTileId(textTileId === undefined ? 'new' : textTileId !== 'new' ? Number(textTileId) : 'new')
        },
    })),
])

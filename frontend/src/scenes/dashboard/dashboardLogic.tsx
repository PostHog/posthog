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
import api, { ApiMethodOptions, getJSONOrNull } from 'lib/api'
import { DashboardPrivilegeLevel, OrganizationMembershipLevel } from 'lib/constants'
import { Dayjs, dayjs, now } from 'lib/dayjs'
import { currentSessionId, TimeToSeeDataPayload } from 'lib/internalMetrics'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { clearDOMTextSelection, isAbortedRequest, shouldCancelQuery, toParams, uuid } from 'lib/utils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { Layout, Layouts } from 'react-grid-layout'
import { calculateLayouts } from 'scenes/dashboard/tileLayouts'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { getQueryBasedDashboard, getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import { pollForResults } from '~/queries/query'
import { DashboardFilter, RefreshType } from '~/queries/schema'
import {
    ActivityScope,
    AnyPropertyFilter,
    Breadcrumb,
    DashboardLayoutSize,
    DashboardMode,
    DashboardPlacement,
    DashboardTemplateEditorType,
    DashboardTile,
    DashboardType,
    InsightColor,
    InsightModel,
    InsightShortId,
    QueryBasedInsightModel,
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

const REFRESH_DASHBOARD_ITEM_ACTION = 'refresh_dashboard_item'
export interface DashboardLogicProps {
    id: number
    dashboard?: DashboardType<QueryBasedInsightModel>
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

async function runWithLimit<T>(tasks: (() => Promise<T>)[], limit: number): Promise<T[]> {
    const results: T[] = []
    const activePromises: Set<Promise<void>> = new Set()
    const remainingTasks = [...tasks]

    const startTask = async (task: () => Promise<T>): Promise<void> => {
        const promise = task()
            .then((result) => {
                results.push(result)
            })
            .catch((error) => {
                console.error('Error executing task:', error)
            })
            .finally(() => {
                void activePromises.delete(promise)
            })
        activePromises.add(promise)
        await promise
    }

    while (remainingTasks.length > 0 || activePromises.size > 0) {
        if (activePromises.size < limit && remainingTasks.length > 0) {
            void startTask(remainingTasks.shift()!)
        } else {
            await Promise.race(activePromises)
        }
    }

    return results
}

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

async function getSingleInsight(
    currentTeamId: number | null,
    insight: QueryBasedInsightModel,
    dashboardId: number,
    queryId: string,
    refresh: RefreshType,
    methodOptions?: ApiMethodOptions,
    filtersOverride?: DashboardFilter
): Promise<QueryBasedInsightModel | null> {
    const apiUrl = `api/projects/${currentTeamId}/insights/${insight.id}/?${toParams({
        refresh,
        from_dashboard: dashboardId, // needed to load insight in correct context
        client_query_id: queryId,
        session_id: currentSessionId(),
        ...(filtersOverride ? { filters_override: filtersOverride } : {}),
    })}`
    const insightResponse: Response = await api.getResponse(apiUrl, methodOptions)
    const legacyInsight: InsightModel | null = await getJSONOrNull(insightResponse)
    return legacyInsight !== null ? getQueryBasedInsightModel(legacyInsight) : null
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
        loadDashboard: (payload: {
            refresh?: RefreshType
            action:
                | 'initial_load'
                | 'update'
                | 'refresh'
                | 'load_missing'
                | 'refresh_insights_on_filters_updated'
                | 'preview'
        }) => payload,
        triggerDashboardUpdate: (payload) => ({ payload }),
        /** The current state in which the dashboard is being viewed, see DashboardMode. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource | null) => ({ mode, source }),
        updateLayouts: (layouts: Layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        updateTileColor: (tileId: number, color: string | null) => ({ tileId, color }),
        removeTile: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),
        refreshDashboardItem: (payload: { tile: DashboardTile<QueryBasedInsightModel> }) => payload,
        refreshAllDashboardItems: (payload: {
            tiles?: DashboardTile<QueryBasedInsightModel>[]
            action: string
            dashboardQueryId?: string
        }) => payload,
        refreshAllDashboardItemsManual: true,
        resetInterval: true,
        updateAndRefreshDashboard: true,
        setDates: (date_from: string | null, date_to: string | null) => ({
            date_from,
            date_to,
        }),
        setProperties: (properties: AnyPropertyFilter[] | null) => ({ properties }),
        setFiltersAndLayouts: (filters: DashboardFilter) => ({ filters }),
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        setRefreshStatus: (shortId: InsightShortId, loading = false, queued = false) => ({ shortId, loading, queued }),
        setRefreshStatuses: (shortIds: InsightShortId[], loading = false, queued = false) => ({
            shortIds,
            loading,
            queued,
        }),
        setPageVisibility: (visible: boolean) => ({ visible }),
        setRefreshError: (shortId: InsightShortId) => ({ shortId }),
        reportDashboardViewed: true, // Reports `viewed dashboard` and `dashboard analyzed` events
        setShouldReportOnAPILoad: (shouldReport: boolean) => ({ shouldReport }), // See reducer for details
        setSubscriptionMode: (enabled: boolean, id?: number | 'new') => ({ enabled, id }),
        moveToDashboard: (
            tile: DashboardTile<QueryBasedInsightModel>,
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
        duplicateTile: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),
        loadingDashboardItemsStarted: (action: string, dashboardQueryId: string) => ({ action, dashboardQueryId }),
        setInitialLoadResponseBytes: (responseBytes: number) => ({ responseBytes }),
        abortQuery: (payload: { dashboardQueryId: string; queryId: string; queryStartTime: number }) => payload,
        abortAnyRunningQuery: true,
        updateFiltersAndLayouts: true,
    }),

    loaders(({ actions, props, values }) => ({
        dashboard: [
            null as DashboardType<QueryBasedInsightModel> | null,
            {
                loadDashboard: async ({ refresh, action }, breakpoint) => {
                    const dashboardQueryId = uuid()
                    actions.loadingDashboardItemsStarted(action, dashboardQueryId)
                    await breakpoint(200)

                    try {
                        const apiUrl = values.apiUrl(
                            refresh || 'async',
                            action === 'preview' ? values.temporaryFilters : undefined
                        )
                        const dashboardResponse: Response = await api.getResponse(apiUrl)
                        const dashboard: DashboardType<InsightModel> | null = await getJSONOrNull(dashboardResponse)

                        actions.setInitialLoadResponseBytes(getResponseBytes(dashboardResponse))

                        // don't update dashboard tile layouts if we're previewing
                        // we want to retain what the user has temporarily set
                        if (action === 'preview' && dashboard) {
                            const editModeTileLayouts: Record<number, DashboardTile['layouts']> = {}
                            values.dashboard?.tiles.forEach((tile: DashboardTile<QueryBasedInsightModel>) => {
                                editModeTileLayouts[tile.id] = tile.layouts
                            })

                            const tilesWithPreviousLayouts = dashboard.tiles.map((tile) => ({
                                ...tile,
                                layouts: editModeTileLayouts?.[tile.id],
                            }))

                            return getQueryBasedDashboard({
                                ...dashboard,
                                tiles: tilesWithPreviousLayouts,
                            })
                        }

                        return getQueryBasedDashboard(dashboard)
                    } catch (error: any) {
                        if (error.status === 404) {
                            return null
                        }
                        throw error
                    }
                },
                updateFiltersAndLayouts: async (_, breakpoint) => {
                    actions.abortAnyRunningQuery()

                    try {
                        const layoutsToUpdate = (values.dashboard?.tiles || []).map((tile) => ({
                            id: tile.id,
                            layouts: tile.layouts,
                        }))

                        breakpoint()

                        const dashboard: DashboardType<InsightModel> = await api.update(
                            `api/projects/${values.currentTeamId}/dashboards/${props.id}`,
                            {
                                filters: values.filters,
                                tiles: layoutsToUpdate,
                            }
                        )
                        return getQueryBasedDashboard(dashboard)
                    } catch (e) {
                        lemonToast.error('Could not update dashboard: ' + String(e))
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
                        } as DashboardType<QueryBasedInsightModel>
                    } catch (e) {
                        lemonToast.error('Could not remove tile from dashboard: ' + String(e))
                        return values.dashboard
                    }
                },
                setDashboardMode: async ({ mode, source }) => {
                    if (
                        mode === null &&
                        source === DashboardEventSource.DashboardHeaderDiscardChanges &&
                        values.dashboard?.tiles
                    ) {
                        // layout changes were discarded so need to reset to original state
                        const restoredTiles = values.dashboard?.tiles?.map((tile) => ({
                            ...tile,
                            layouts: values.dashboardLayouts?.[tile.id],
                        }))

                        values.dashboard.tiles = restoredTiles
                    }

                    return values.dashboard
                },
                duplicateTile: async ({ tile }) => {
                    try {
                        const newTile = { ...tile } as Partial<DashboardTile<QueryBasedInsightModel>>
                        delete newTile.id
                        if (newTile.text) {
                            newTile.text = { body: newTile.text.body } as TextModel
                        }

                        const dashboard: DashboardType<InsightModel> = await api.update(
                            `api/projects/${values.currentTeamId}/dashboards/${props.id}`,
                            {
                                tiles: [newTile],
                            }
                        )
                        return getQueryBasedDashboard(dashboard)
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
                    }
                    const dashboard: DashboardType<InsightModel> = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/dashboards/${props.id}/move_tile`,
                        {
                            tile,
                            toDashboard,
                        }
                    )
                    return getQueryBasedDashboard(dashboard)
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        _dashboardLoading: [
            false,
            {
                loadDashboard: () => true,
                loadDashboardSuccess: () => false,
                loadDashboardFailure: () => false,
            },
        ],
        pageVisibility: [
            true,
            {
                setPageVisibility: (_, { visible }) => visible,
            },
        ],
        dashboardFailedToLoad: [
            false,
            {
                loadDashboardSuccess: () => false,
                loadDashboardFailure: () => true,
            },
        ],
        dashboardLayouts: [
            {} as Record<DashboardTile['id'], DashboardTile['layouts']>,
            {
                loadDashboardSuccess: (state, { dashboard, payload }) => {
                    // don't update dashboardLayouts if we're previewing
                    if (payload?.action === 'preview') {
                        return state
                    }

                    const tileIdToLayouts: Record<number, DashboardTile['layouts']> = {}
                    dashboard?.tiles.forEach((tile: DashboardTile<QueryBasedInsightModel>) => {
                        tileIdToLayouts[tile.id] = tile.layouts
                    })

                    return tileIdToLayouts
                },
            },
        ],
        temporaryFilters: [
            {
                date_from: null,
                date_to: null,
                properties: null,
            } as DashboardFilter,
            {
                setDates: (state, { date_from, date_to }) => ({
                    ...state,
                    date_from: date_from || null,
                    date_to: date_to || null,
                }),
                setProperties: (state, { properties }) => ({
                    ...state,
                    properties: properties || null,
                }),
                loadDashboardSuccess: (state, { dashboard }) =>
                    dashboard
                        ? {
                              ...state,
                              date_from: dashboard?.filters.date_from || null,
                              date_to: dashboard?.filters.date_to || null,
                              properties: dashboard?.filters.properties || [],
                          }
                        : state,
            },
        ],
        filters: [
            {
                date_from: null,
                date_to: null,
                properties: null,
            } as DashboardFilter,
            {
                setFiltersAndLayouts: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                loadDashboardSuccess: (state, { dashboard, payload }) =>
                    dashboard
                        ? {
                              ...state,
                              // don't update filters if we're previewing
                              ...(payload?.action === 'preview'
                                  ? {}
                                  : {
                                        date_from: dashboard?.filters.date_from || null,
                                        date_to: dashboard?.filters.date_to || null,
                                        properties: dashboard?.filters.properties || [],
                                    }),
                          }
                        : state,
            },
        ],
        dashboard: [
            null as DashboardType<QueryBasedInsightModel> | null,
            {
                updateLayouts: (state, { layouts }) => {
                    const itemLayouts = layoutsByTile(layouts)

                    return {
                        ...state,
                        tiles: state?.tiles?.map((tile) => ({ ...tile, layouts: itemLayouts[tile.id] })),
                    } as DashboardType<QueryBasedInsightModel>
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
                [dashboardsModel.actionTypes.updateDashboardInsight]: (state, { insight, extraDashboardIds }) => {
                    const targetDashboards = (insight.dashboard_tiles || [])
                        .map((tile) => tile.dashboard_id)
                        .concat(extraDashboardIds || [])
                    if (!targetDashboards.includes(props.id)) {
                        // this update is not for this dashboard
                        return state
                    }

                    if (state) {
                        const tileIndex = state.tiles.findIndex(
                            (t) => !!t.insight && t.insight.short_id === insight.short_id
                        )

                        const newTiles = state.tiles.slice()

                        if (tileIndex >= 0) {
                            if (insight.dashboards?.includes(props.id)) {
                                newTiles[tileIndex] = {
                                    ...newTiles[tileIndex],
                                    insight: insight,
                                }
                            } else if (!insight.dashboards?.includes(props.id)) {
                                newTiles.splice(tileIndex, 1)
                            }
                        } else {
                            // we can't create tiles in this reducer
                            // will reload all items in a listener to pick up the new tile
                        }

                        return {
                            ...state,
                            tiles: newTiles.filter((t) => !t.deleted || !t.insight?.deleted),
                        } as DashboardType<QueryBasedInsightModel>
                    }

                    return null
                },
                [dashboardsModel.actionTypes.updateDashboardSuccess]: (state, { dashboard }) => {
                    return state && dashboard && state.id === dashboard.id ? dashboard : state
                },
                [insightsModel.actionTypes.renameInsightSuccess]: (
                    state,
                    { item }
                ): DashboardType<QueryBasedInsightModel> | null => {
                    const tileIndex = state?.tiles.findIndex((t) => !!t.insight && t.insight.short_id === item.short_id)
                    const tiles = state?.tiles.slice(0)

                    if (tileIndex === undefined || tileIndex === -1 || !tiles) {
                        return state
                    }

                    tiles[tileIndex] = {
                        ...tiles[tileIndex],
                        insight: {
                            ...(tiles[tileIndex].insight as QueryBasedInsightModel),
                            name: item.name,
                            last_modified_at: item.last_modified_at,
                        },
                    }

                    return {
                        ...state,
                        tiles,
                    } as DashboardType<QueryBasedInsightModel>
                },
            },
        ],
        loadTimer: [null as Date | null, { loadDashboard: () => new Date() }],
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
            to `loadDashboard` is completed (e.g. if you open PH directly to a dashboard)
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
                return (refresh?: RefreshType, filtersOverride?: DashboardFilter) =>
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}/?${toParams({
                        refresh,
                        filters_override: filtersOverride,
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
            (s) => [s._dashboardLoading, s.refreshStatus],
            (dashboardLoading, refreshStatus) => {
                return dashboardLoading || Object.values(refreshStatus).some((s) => s.loading || s.queued)
            },
        ],
        isRefreshingQueued: [(s) => [s.refreshStatus], (refreshStatus) => (id: string) => !!refreshStatus[id]?.queued],
        isRefreshing: [(s) => [s.refreshStatus], (refreshStatus) => (id: string) => !!refreshStatus[id]?.loading],
        highlightedInsightId: [
            () => [router.selectors.searchParams],
            (searchParams) => searchParams.highlightInsightId,
        ],
        sortedDates: [
            (s) => [s.insightTiles],
            (insightTiles): Dayjs[] => {
                if (!insightTiles || !insightTiles.length) {
                    return []
                }

                const validDates = insightTiles
                    .map((i) => dayjs(i.insight?.last_refresh))
                    .filter((date) => date.isValid())
                return sortDayJsDates(validDates)
            },
        ],
        newestRefreshed: [
            // page visibility is only here to trigger a recompute when the page is hidden/shown
            (s) => [s.sortedDates, s.pageVisibility],
            (sortedDates): Dayjs | null => {
                if (!sortedDates.length) {
                    return null
                }

                return sortedDates[sortedDates.length - 1]
            },
        ],
        sortedClientRefreshAllowed: [
            (s) => [s.insightTiles],
            (insightTiles): Dayjs[] => {
                if (!insightTiles || !insightTiles.length) {
                    return []
                }

                const validDates = insightTiles
                    .filter((i) => !!i.insight?.cache_target_age || !!i.insight?.next_allowed_client_refresh)
                    .map((i) => dayjs(i.insight?.cache_target_age ?? i.insight?.next_allowed_client_refresh))
                    .filter((date) => date.isValid())
                return sortDayJsDates(validDates)
            },
        ],
        oldestClientRefreshAllowed: [
            (s) => [s.sortedClientRefreshAllowed],
            (sortedClientRefreshAllowed): Dayjs | null => {
                if (!sortedClientRefreshAllowed.length) {
                    return null
                }

                return sortedClientRefreshAllowed[0]
            },
        ],
        blockRefresh: [
            // page visibility is only here to trigger a recompute when the page is hidden/shown
            (s) => [s.newestRefreshed, s.placement, s.oldestClientRefreshAllowed, s.pageVisibility],
            (newestRefreshed: Dayjs, placement: DashboardPlacement, oldestClientRefreshAllowed: Dayjs | null) => {
                return (
                    !!newestRefreshed &&
                    !(placement === DashboardPlacement.FeatureFlag) &&
                    oldestClientRefreshAllowed?.isAfter(now())
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
            (s) => [s.dashboard, s._dashboardLoading, s.dashboardFailedToLoad],
            (dashboard, dashboardLoading, dashboardFailedToLoad): Breadcrumb[] => [
                {
                    key: Scene.Dashboards,
                    name: 'Dashboards',
                    path: urls.dashboards(),
                },
                {
                    key: [Scene.Dashboard, dashboard?.id || 'new'],
                    name: dashboard?.id
                        ? dashboard.name
                        : dashboardFailedToLoad
                        ? 'Could not load'
                        : !dashboardLoading
                        ? 'Not found'
                        : null,
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

        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.dashboard],
            (dashboard): SidePanelSceneContext | null => {
                return dashboard
                    ? {
                          activity_scope: ActivityScope.DASHBOARD,
                          activity_item_id: `${dashboard.id}`,
                          access_control_resource: 'dashboard',
                          access_control_resource_id: `${dashboard.id}`,
                      }
                    : null
            },
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
                    }
                    return 0
                })
            },
        ],
    })),
    events(({ actions, cache, props }) => ({
        afterMount: () => {
            if (props.id) {
                if (props.dashboard) {
                    // If we already have dashboard data, use it. Should the data turn out to be stale,
                    // the loadDashboardSuccess listener will initiate a refresh
                    actions.loadDashboardSuccess(props.dashboard)
                } else {
                    actions.loadDashboard({
                        refresh: 'lazy_async',
                        action: 'initial_load',
                    })
                }
            }
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
        updateFiltersAndLayoutsSuccess: () => {
            actions.loadDashboard({ action: 'update' })
        },
        setRefreshError: sharedListeners.reportRefreshTiming,
        setRefreshStatuses: sharedListeners.reportRefreshTiming,
        setRefreshStatus: sharedListeners.reportRefreshTiming,
        loadDashboardFailure: () => {
            const { action, dashboardQueryId, startTime } = values.dashboardLoadTimerData

            eventUsageLogic.actions.reportTimeToSeeData({
                team_id: values.currentTeamId,
                type: 'dashboard_load',
                context: 'dashboard',
                status: 'failure',
                action,
                primary_interaction_id: dashboardQueryId,
                time_to_see_data_ms: Math.floor(performance.now() - startTime),
            })
        },
        [insightsModel.actionTypes.duplicateInsightSuccess]: () => {
            // TODO this is a bit hacky, but we need to reload the dashboard to get the new insight
            // TODO when duplicated from a dashboard we should carry the context so only one logic needs to reload
            // TODO or we should duplicate the tile (and implicitly the insight)
            actions.loadDashboard({ action: 'update' })
        },
        [dashboardsModel.actionTypes.tileAddedToDashboard]: ({ dashboardId }) => {
            // when adding an insight to a dashboard, we need to reload the dashboard to get the new insight
            if (dashboardId === props.id) {
                actions.loadDashboard({ action: 'update' })
            }
        },
        [dashboardsModel.actionTypes.updateDashboardInsight]: ({ insight, extraDashboardIds }) => {
            const targetDashboards = (insight.dashboard_tiles || [])
                .map((tile) => tile.dashboard_id)
                .concat(extraDashboardIds || [])
            if (!targetDashboards.includes(props.id)) {
                // this update is not for this dashboard
                return
            }

            const tileIndex = values.tiles.findIndex((t) => !!t.insight && t.insight.short_id === insight.short_id)

            if (tileIndex === -1) {
                // this is a new tile created from an insight context we need to reload the dashboard
                actions.loadDashboard({ action: 'update' })
            }
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
            actions.loadDashboard({ action: 'refresh' })
        },
        refreshDashboardItem: async ({ tile }, breakpoint) => {
            const dashboardId: number = props.id
            const insight = tile.insight

            if (!insight) {
                return
            }

            actions.setRefreshStatus(insight.short_id, true, true)

            try {
                breakpoint()
                const refreshedInsight = await getSingleInsight(
                    values.currentTeamId,
                    insight,
                    dashboardId,
                    uuid(),
                    'force_async'
                )
                dashboardsModel.actions.updateDashboardInsight(refreshedInsight!)
                // Start polling for results
                tile.insight = refreshedInsight!
                actions.refreshAllDashboardItems({ tiles: [tile], action: REFRESH_DASHBOARD_ITEM_ACTION })
            } catch (e: any) {
                actions.setRefreshError(insight.short_id)
            }
        },
        refreshAllDashboardItems: async ({ tiles, action, dashboardQueryId = uuid() }, breakpoint) => {
            const dashboardId: number = props.id

            const insightsToRefresh = (tiles || values.insightTiles || [])
                .filter((t) => {
                    if (t.insight?.query_status) {
                        return true
                    }
                })
                .map((t) => t.insight)
                .filter((i): i is QueryBasedInsightModel => !!i)

            // Don't do anything if there's nothing to refresh
            if (insightsToRefresh.length === 0) {
                // still report time to see updated data
                // in case loadDashboard found all cached insights
                const dashboard = values.dashboard
                if (dashboard && action !== REFRESH_DASHBOARD_ITEM_ACTION) {
                    const { action, dashboardQueryId, startTime, responseBytes } = values.dashboardLoadTimerData
                    const lastRefresh = sortDates(dashboard.tiles.map((tile) => tile.insight?.last_refresh || null))

                    eventUsageLogic.actions.reportTimeToSeeData({
                        team_id: values.currentTeamId,
                        type: 'dashboard_load',
                        context: 'dashboard',
                        action,
                        status: 'success',
                        primary_interaction_id: dashboardQueryId,
                        time_to_see_data_ms: Math.floor(performance.now() - startTime),
                        api_response_bytes: responseBytes,
                        insights_fetched: dashboard.tiles.length,
                        insights_fetched_cached: dashboard.tiles.reduce(
                            (acc, curr) => acc + (curr.is_cached ? 1 : 0),
                            0
                        ),
                        min_last_refresh: lastRefresh[0],
                        max_last_refresh: lastRefresh[lastRefresh.length - 1],
                    })
                }

                return
            }

            let cancelled = false
            actions.setRefreshStatuses(
                insightsToRefresh.map((item) => item.short_id),
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
            const totalResponseBytes = 0

            // array of functions that reload each insight
            const fetchItemFunctions = insightsToRefresh.map((insight) => async () => {
                // dashboard refresh or insight refresh will have been triggered first
                // so we should have a query_id to poll for
                const queryId = insight?.query_status?.id
                const queryStartTime = performance.now()

                try {
                    breakpoint()
                    if (queryId) {
                        await pollForResults(queryId, false, methodOptions)
                        const currentTeamId = values.currentTeamId
                        // TODO: Check and remove - We get the insight again here to get everything in the right format (e.g. because of result vs results)
                        const polledInsight = await getSingleInsight(
                            currentTeamId,
                            insight,
                            dashboardId,
                            queryId,
                            'force_cache',
                            methodOptions,
                            action === 'preview' ? values.temporaryFilters : undefined
                        )

                        if (action === 'preview' && polledInsight!.dashboard_tiles) {
                            // if we're previewing, only update the insight on this dashboard
                            polledInsight!.dashboards = [dashboardId]
                        }
                        dashboardsModel.actions.updateDashboardInsight(polledInsight!)
                        actions.setRefreshStatus(insight.short_id)
                    }
                } catch (e: any) {
                    if (isBreakpoint(e)) {
                        cancelled = true
                    } else if (shouldCancelQuery(e)) {
                        if (!cancelled && queryId) {
                            // cancel all insight requests for this query in one go
                            actions.abortQuery({ dashboardQueryId: dashboardQueryId, queryId, queryStartTime })
                        }
                        if (isAbortedRequest(e)) {
                            cancelled = true
                        }
                    } else {
                        actions.setRefreshError(insight.short_id)
                    }
                }

                refreshesFinished += 1
                if (!cancelled && refreshesFinished === insightsToRefresh.length) {
                    const payload: TimeToSeeDataPayload = {
                        team_id: values.currentTeamId,
                        type: 'dashboard_load',
                        context: 'dashboard',
                        action,
                        status: 'success',
                        primary_interaction_id: dashboardQueryId,
                        api_response_bytes: totalResponseBytes,
                        time_to_see_data_ms: Math.floor(performance.now() - refreshStartTime),
                        insights_fetched: insightsToRefresh.length,
                        insights_fetched_cached: 0,
                    }

                    eventUsageLogic.actions.reportTimeToSeeData(payload)
                }
            })

            await runWithLimit(fetchItemFunctions, 2)

            eventUsageLogic.actions.reportDashboardRefreshed(dashboardId, values.newestRefreshed)
        },
        setFiltersAndLayouts: ({ filters: { date_from, date_to } }) => {
            actions.updateFiltersAndLayouts()
            eventUsageLogic.actions.reportDashboardDateRangeChanged(date_from, date_to)
            eventUsageLogic.actions.reportDashboardPropertiesChanged()
        },
        setDashboardMode: async ({ mode, source }) => {
            if (mode === DashboardMode.Edit) {
                clearDOMTextSelection()
                lemonToast.info('Now editing the dashboard – save to persist changes')
            } else if (mode === null) {
                if (source === DashboardEventSource.DashboardHeaderDiscardChanges) {
                    // cancel edit mode changes

                    // reset filters to that before previewing
                    actions.setDates(values.filters.date_from ?? null, values.filters.date_to ?? null)
                    actions.setProperties(values.filters.properties ?? null)

                    // also reset layout to that we stored in dashboardLayouts
                    // this is done in the reducer for dashboard
                } else if (source === DashboardEventSource.DashboardHeaderSaveDashboard) {
                    // save edit mode changes
                    actions.setFiltersAndLayouts(values.temporaryFilters)
                }
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
                    values.newestRefreshed &&
                    values.newestRefreshed.isBefore(now().subtract(values.autoRefresh.interval, 'seconds'))
                ) {
                    actions.loadDashboard({ action: 'refresh' })
                }
                cache.autoRefreshInterval = window.setInterval(() => {
                    actions.loadDashboard({ action: 'refresh' })
                }, values.autoRefresh.interval * 1000)
            }
        },
        loadDashboardSuccess: function (...args) {
            void sharedListeners.reportLoadTiming(...args)

            if (!values.dashboard) {
                return // We hit a 404
            }

            const { action, dashboardQueryId } = values.dashboardLoadTimerData
            actions.refreshAllDashboardItems({ action, dashboardQueryId })

            if (values.shouldReportOnAPILoad) {
                actions.setShouldReportOnAPILoad(false)
                actions.reportDashboardViewed()
            }
        },
        reportDashboardViewed: async (_, breakpoint) => {
            // Caching `dashboard`, as the dashboard might have unmounted after the breakpoint,
            // and "values.dashboard" will then fail
            const { dashboard, newestRefreshed } = values
            if (dashboard) {
                eventUsageLogic.actions.reportDashboardViewed(dashboard, newestRefreshed)
                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish
                if (
                    router.values.location.pathname === urls.dashboard(dashboard.id) ||
                    router.values.location.pathname === urls.projectHomepage() ||
                    router.values.location.pathname.startsWith(urls.sharedDashboard(''))
                ) {
                    eventUsageLogic.actions.reportDashboardViewed(dashboard, newestRefreshed, 10)
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
            eventUsageLogic.actions.reportTimeToSeeData({
                team_id: values.currentTeamId,
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
        setProperties: () => {
            actions.loadDashboard({ action: 'preview' })
        },
        setDates: () => {
            actions.loadDashboard({ action: 'preview' })
        },
    })),

    urlToAction(({ values, actions }) => ({
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
            if (values.dashboardMode === DashboardMode.Sharing) {
                actions.setDashboardMode(null, null)
            }
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

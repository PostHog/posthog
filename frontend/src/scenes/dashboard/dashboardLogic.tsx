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
import api, { getJSONOrThrow } from 'lib/api'
import { dashboardsModel } from '~/models/dashboardsModel'
import { router, urlToAction } from 'kea-router'
import { areObjectValuesEmpty, clearDOMTextSelection, isUserLoggedIn, toParams, uuid } from 'lib/utils'
import { insightsModel } from '~/models/insightsModel'
import {
    AUTO_REFRESH_DASHBOARD_THRESHOLD_HOURS,
    DashboardPrivilegeLevel,
    OrganizationMembershipLevel,
} from 'lib/constants'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    AnyPropertyFilter,
    Breadcrumb,
    ChartDisplayType,
    DashboardLayoutSize,
    DashboardMode,
    DashboardPlacement,
    DashboardTile,
    DashboardType,
    FilterType,
    InsightColor,
    InsightModel,
    InsightShortId,
    TextModel,
    TileLayout,
} from '~/types'
import type { dashboardLogicType } from './dashboardLogicType'
import { Layout, Layouts } from 'react-grid-layout'
import { insightLogic } from 'scenes/insights/insightLogic'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { dayjs, now } from 'lib/dayjs'
import { lemonToast } from 'lib/components/lemonToast'
import { Link } from 'lib/components/Link'
import { isPathsFilter, isRetentionFilter, isTrendsFilter } from 'scenes/insights/sharedUtils'
import { captureTimeToSeeData, TimeToSeeDataPayload } from 'lib/internalMetrics'
import { getResponseBytes, sortDates } from '../insights/utils'
import { loaders } from 'kea-loaders'

export const BREAKPOINTS: Record<DashboardLayoutSize, number> = {
    sm: 1024,
    xs: 0,
}
export const BREAKPOINT_COLUMN_COUNTS: Record<DashboardLayoutSize, number> = { sm: 12, xs: 1 }
export const MIN_ITEM_WIDTH_UNITS = 3
export const MIN_ITEM_HEIGHT_UNITS = 5

const IS_TEST_MODE = process.env.NODE_ENV === 'test'

export interface DashboardLogicProps {
    id?: number
    dashboard?: DashboardType
    placement?: DashboardPlacement
}

export interface RefreshStatus {
    loading?: boolean
    refreshed?: boolean
    error?: boolean
    timer?: Date | null
}

export const AUTO_REFRESH_INITIAL_INTERVAL_SECONDS = 300

export type LoadDashboardItemsProps = { refresh?: boolean; action: string }

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
        values: [teamLogic, ['currentTeamId']],
        logic: [dashboardsModel, insightsModel, eventUsageLogic],
    })),

    props({} as DashboardLogicProps),

    key((props) => {
        if (typeof props.id === 'string') {
            throw Error('Must init dashboardLogic with a numeric key')
        }
        return props.id ?? 'new'
    }),

    actions({
        loadExportedDashboard: (dashboard: DashboardType | null) => ({ dashboard }),
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
        setDates: (dateFrom: string | null, dateTo: string | null, reloadDashboard = true) => ({
            dateFrom,
            dateTo,
            reloadDashboard,
        }),
        setProperties: (properties: AnyPropertyFilter[]) => ({ properties }),
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        setRefreshStatus: (shortId: InsightShortId, loading = false) => ({ shortId, loading }),
        setRefreshStatuses: (shortIds: InsightShortId[], loading = false) => ({ shortIds, loading }),
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
    }),

    loaders(({ actions, props, values }) => ({
        // TODO this is a terrible name... it is "dashboard" but there's a "dashboard" reducer ¯\_(ツ)_/¯
        allItems: [
            null as DashboardType | null,
            {
                loadDashboardItems: async ({ refresh, action }) => {
                    if (!props.id) {
                        console.warn('Called `loadDashboardItems` but ID is not set.')
                        return null
                    }

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
                updateTileColor: async ({ tileId, color }) => {
                    if (!props.id) {
                        // what are we saving colors against?!
                        return values.allItems
                    }

                    await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                        tiles: [{ id: tileId, color }],
                        no_items_field: true,
                    })
                    const matchingTile = values.tiles.find((tile) => tile.id === tileId)
                    if (matchingTile) {
                        matchingTile.color = color as InsightColor
                    }
                    return values.allItems
                },
                removeTile: async ({ tile }) => {
                    try {
                        await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                            tiles: [{ id: tile.id, deleted: true }],
                            no_items_field: true,
                        })
                        dashboardsModel.actions.tileRemovedFromDashboard({
                            tile: tile,
                            dashboardId: props.id,
                        })

                        return {
                            ...values.allItems,
                            tiles: values.tiles.filter((t) => t.id !== tile.id),
                        } as DashboardType
                    } catch (e) {
                        lemonToast.error('Could not remove tile from dashboard: ' + e)
                        return values.allItems
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
                            no_items_field: true,
                        } as Partial<InsightModel>)
                    } catch (e) {
                        lemonToast.error('Could not duplicate tile: ' + e)
                        return values.allItems
                    }
                },
                moveToDashboard: async ({ tile, fromDashboard, toDashboard }) => {
                    if (!tile || fromDashboard === toDashboard) {
                        return values.allItems
                    }

                    if (fromDashboard !== props.id) {
                        return values.allItems
                    } else {
                        return await api.update(
                            `api/projects/${teamLogic.values.currentTeamId}/dashboards/${props.id}/move_tile`,
                            {
                                tile,
                                toDashboard,
                                no_items_field: true,
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
            },
        ],
        filters: [
            { date_from: null, date_to: null } as FilterType,
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
                loadDashboardItemsSuccess: (state, { allItems }) => ({
                    ...state,
                    date_from: allItems?.filters.date_from || null,
                    date_to: allItems?.filters.date_to || null,
                }),
            },
        ],
        allItems: [
            null as DashboardType | null,
            {
                loadExportedDashboard: (_, { dashboard }) => dashboard,
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
                    if (!props.id) {
                        // what are we even updating?
                        return state
                    }
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
                [dashboardsModel.actionTypes.updateDashboardTile]: (state, { tile, extraDashboardIds }) => {
                    const targetDashboards = (tile.insight?.dashboards || []).concat(extraDashboardIds || [])

                    if (!props.id) {
                        // what are we even updating?
                        return state
                    }
                    if (!targetDashboards.includes(props.id)) {
                        // this update is not for this dashboard
                        return state
                    }

                    if (state) {
                        const tileIndex = state.tiles.findIndex((t) => t.id === tile.id)
                        const newTiles = state.tiles.slice(0)
                        if (tileIndex >= 0) {
                            if (!!tile.text || tile.insight?.dashboards?.includes(props.id)) {
                                newTiles[tileIndex] = { ...newTiles[tileIndex], ...tile }
                            } else {
                                newTiles.splice(tileIndex, 1)
                            }
                        } else {
                            newTiles.push(tile)
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
                            ...((tiles[tileIndex] as DashboardTile).insight as InsightModel),
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
                setRefreshStatus: (state, { shortId, loading }) => ({
                    ...state,
                    [shortId]: loading
                        ? { loading: true, timer: new Date() }
                        : { refreshed: true, timer: state[shortId]?.timer || null },
                }),
                setRefreshStatuses: (state, { shortIds, loading }) =>
                    Object.fromEntries(
                        shortIds.map((shortId) => [
                            shortId,
                            loading
                                ? { loading: true, timer: new Date() }
                                : { refreshed: true, timer: state[shortId]?.timer || null },
                        ])
                    ) as Record<string, RefreshStatus>,
                setRefreshError: (state, { shortId }) => ({
                    ...state,
                    [shortId]: { error: true, timer: state[shortId]?.timer || null },
                }),
                refreshAllDashboardItems: () => ({}),
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
            { persist: true, prefix: '1_' },
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
    selectors(({ actions }) => ({
        asDashboardTemplate: [
            (s) => [s.allItems],
            (dashboard: DashboardType): string => {
                return dashboard
                    ? JSON.stringify(
                          {
                              template_name: dashboard.name,
                              description: dashboard.description,
                              dashboard_filters: dashboard.filters,
                              tags: dashboard.tags || [],
                              tiles: dashboard.tiles.map((tile) => {
                                  if (!!tile.text) {
                                      return {
                                          type: 'TEXT',
                                          body: tile.text.body,
                                          layouts: tile.layouts,
                                          color: tile.color,
                                      }
                                  }
                                  if (!!tile.insight) {
                                      return {
                                          type: 'INSIGHT',
                                          name: tile.insight.name,
                                          description: tile.insight.description || '',
                                          filters: tile.insight.filters,
                                          layouts: tile.layouts,
                                          color: tile.color,
                                      }
                                  }
                                  throw new Error('Unknown tile type')
                              }),
                          },
                          undefined,
                          4
                      )
                    : ''
            },
        ],
        placement: [() => [(_, props) => props.placement], (placement) => placement ?? DashboardPlacement.Dashboard],
        apiUrl: [
            () => [(_, props) => props.id],
            (id) => {
                return (refresh?: boolean) =>
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}/?${toParams({
                        refresh,
                        no_items_field: true,
                    })}`
            },
        ],
        tiles: [(s) => [s.allItems], (allItems) => allItems?.tiles?.filter((t) => !t.deleted) || []],
        insightTiles: [
            (s) => [s.tiles],
            (tiles) => tiles.filter((t) => !!t.insight).filter((i) => !i.insight?.deleted),
        ],
        textTiles: [(s) => [s.tiles], (tiles) => tiles.filter((t) => !!t.text)],
        itemsLoading: [
            (s) => [s.allItemsLoading, s.refreshStatus],
            (allItemsLoading, refreshStatus) => {
                return allItemsLoading || Object.values(refreshStatus).some((s) => s.loading)
            },
        ],
        isRefreshing: [(s) => [s.refreshStatus], (refreshStatus) => (id: string) => !!refreshStatus[id]?.loading],
        highlightedInsightId: [
            () => [router.selectors.searchParams],
            (searchParams) => searchParams.highlightInsightId,
        ],
        lastRefreshed: [
            (s) => [s.insightTiles],
            (insightTiles) => {
                if (!insightTiles || !insightTiles.length) {
                    return null
                }

                const oldest = sortDates(insightTiles.map((i) => i.last_refresh))
                const candidateShortest = oldest.length > 0 ? dayjs(oldest[0]) : null
                return candidateShortest?.isValid() ? candidateShortest : null
            },
        ],
        dashboard: [
            () => [dashboardsModel.selectors.nameSortedDashboards, (_, { id }) => id],
            (dashboards, id): DashboardType | null => {
                return dashboards.find((d) => d.id === id) || null
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
        layouts: [
            (s) => [s.tiles],
            (tiles) => {
                const tilesWithNoLayout = tiles.filter((t) => !t.layouts || areObjectValuesEmpty(t.layouts))

                const allLayouts: Partial<Record<keyof typeof BREAKPOINT_COLUMN_COUNTS, Layout[]>> = {}

                for (const col of Object.keys(BREAKPOINT_COLUMN_COUNTS) as (keyof typeof BREAKPOINT_COLUMN_COUNTS)[]) {
                    // The dashboard redesign includes constraints on the size of dashboard items
                    const minW = col === 'xs' ? 1 : MIN_ITEM_WIDTH_UNITS
                    const minH = MIN_ITEM_HEIGHT_UNITS

                    const layouts = tiles.map((tile) => {
                        const filters: Partial<FilterType> | undefined = tile.insight?.filters
                        const isRetention = isRetentionFilter(filters)
                        const isPathsViz = isPathsFilter(filters)
                        const isBoldNumber = isTrendsFilter(filters) && filters.display === ChartDisplayType.BoldNumber

                        const defaultWidth = isRetention || isPathsViz ? 8 : 6
                        const defaultHeight = !!tile.text ? minH + 1 : isRetention ? 8 : isPathsViz ? 12.5 : 5
                        const layout = tile.layouts && tile.layouts[col]
                        const { x, y, w, h } = layout || {}
                        const width = Math.min(w || defaultWidth, BREAKPOINT_COLUMN_COUNTS[col])
                        return {
                            i: tile.id?.toString(),
                            x: Number.isInteger(x) && x + width - 1 < BREAKPOINT_COLUMN_COUNTS[col] ? x : 0,
                            y: Number.isInteger(y) ? y : Infinity,
                            w: width,
                            h: h || defaultHeight,
                            minW,
                            minH: tile.text ? 2 : isBoldNumber ? 4 : minH,
                        }
                    })

                    const cleanLayouts = layouts?.filter(({ y }) => y !== Infinity)

                    // array of -1 for each column
                    const lowestPoints = Array.from(Array(BREAKPOINT_COLUMN_COUNTS[col])).map(() => -1)

                    // set the lowest point for each column
                    cleanLayouts?.forEach(({ x, y, w, h }) => {
                        for (let i = x; i <= x + w - 1; i++) {
                            lowestPoints[i] = Math.max(lowestPoints[i], y + h - 1)
                        }
                    })

                    layouts
                        ?.filter(({ y }) => y === Infinity)
                        .forEach(({ i, w, h }) => {
                            // how low are things in "w" consecutive of columns
                            const segmentCount = BREAKPOINT_COLUMN_COUNTS[col] - w + 1
                            const lowestSegments = Array.from(Array(segmentCount)).map(() => -1)
                            for (let k = 0; k < segmentCount; k++) {
                                for (let j = k; j <= k + w - 1; j++) {
                                    lowestSegments[k] = Math.max(lowestSegments[k], lowestPoints[j])
                                }
                            }

                            let lowestIndex = 0
                            let lowestDepth = lowestSegments[0]

                            lowestSegments.forEach((depth, index) => {
                                if (depth < lowestDepth) {
                                    lowestIndex = index
                                    lowestDepth = depth
                                }
                            })

                            cleanLayouts?.push({
                                i,
                                x: lowestIndex,
                                y: lowestDepth + 1,
                                w,
                                h,
                                minW,
                                minH,
                            })

                            for (let k = lowestIndex; k <= lowestIndex + w - 1; k++) {
                                lowestPoints[k] = Math.max(lowestPoints[k], lowestDepth + h)
                            }
                        })

                    allLayouts[col] = cleanLayouts
                }

                if (tilesWithNoLayout.length > 0) {
                    const layoutsByTileId = layoutsByTile(allLayouts)
                    actions.saveLayouts(
                        tilesWithNoLayout.map((t) => ({
                            id: t.id,
                            layouts: layoutsByTileId[t.id],
                        }))
                    )
                }
                return allLayouts
            },
        ],
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
                    completed: total - (Object.values(refreshStatus).filter((s) => s.loading).length ?? 0),
                    total,
                }
            },
        ],
        breadcrumbs: [
            (s) => [s.allItems],
            (allItems): Breadcrumb[] => [
                {
                    name: 'Dashboards',
                    path: urls.dashboards(),
                },
                {
                    name: allItems?.id ? allItems.name || 'Unnamed' : null,
                },
            ],
        ],
    })),
    events(({ actions, cache, props }) => ({
        afterMount: () => {
            if (props.id) {
                if (props.dashboard) {
                    actions.loadExportedDashboard(props.dashboard)
                } else {
                    actions.loadDashboardItems({
                        refresh: false,
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
            if (!props.id) {
                // what even is loading?!
                return
            }
            if (values.loadTimer) {
                const loadingMilliseconds = new Date().getTime() - values.loadTimer.getTime()
                eventUsageLogic.actions.reportDashboardLoadingTime(loadingMilliseconds, props.id)
            }
        },
    })),
    listeners(({ actions, values, cache, props, sharedListeners }) => ({
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
            if (!props.id) {
                // what are we even updating?
                return
            }
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
            if (!props.id) {
                // what are we saving layouts against?!
                return
            }

            const layoutsToUpdate = tilesToSave.length
                ? tilesToSave
                : (values.allItems?.tiles || []).map((tile) => ({ id: tile.id, layouts: tile.layouts }))

            breakpoint()

            return await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                tiles: layoutsToUpdate,
                no_items_field: true,
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
            actions.refreshAllDashboardItems({ action: 'refresh_manual' })
        },
        refreshAllDashboardItems: async ({ tiles, action, initialLoad, dashboardQueryId }, breakpoint) => {
            if (!props.id) {
                // what are we loading the insight card on?!
                return
            }
            const dashboardId: number = props.id

            const insights = (tiles || values.insightTiles || [])
                .map((t) => t.insight)
                .filter((i): i is InsightModel => !!i)

            // Don't do anything if there's nothing to refresh
            if (insights.length === 0) {
                return
            }

            let breakpointTriggered = false
            actions.setRefreshStatuses(
                insights.map((item) => item.short_id),
                true
            )

            const refreshStartTime = performance.now()
            dashboardQueryId = dashboardQueryId ?? uuid()
            let refreshesFinished = 0
            let totalResponseBytes = 0

            // array of functions that reload each item
            const fetchItemFunctions = insights.map((insight) => async () => {
                // :TODO: Support query cancellation and use this queryId in the actual query.
                const queryId = `${dashboardQueryId}::${uuid()}`
                const queryStartTime = performance.now()
                const apiUrl = `api/projects/${values.currentTeamId}/insights/${insight.id}/?${toParams({
                    refresh: true,
                    from_dashboard: dashboardId, // needed to load insight in correct context
                })}`

                try {
                    breakpoint()

                    const refreshedInsightResponse: Response = await api.getResponse(apiUrl)
                    const refreshedInsight: InsightModel = await getJSONOrThrow(refreshedInsightResponse)
                    breakpoint()
                    updateExistingInsightState({ cachedInsight: insight, dashboardId, refreshedInsight })
                    dashboardsModel.actions.updateDashboardInsight(
                        refreshedInsight,
                        [],
                        props.id ? [props.id] : undefined
                    )
                    actions.setRefreshStatus(insight.short_id)

                    captureTimeToSeeData(values.currentTeamId, {
                        type: 'insight_load',
                        context: 'dashboard',
                        dashboard_query_id: dashboardQueryId,
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
                    console.error(e)
                    if (isBreakpoint(e)) {
                        breakpointTriggered = true
                    } else {
                        actions.setRefreshError(insight.short_id)
                    }
                }

                refreshesFinished += 1
                if (refreshesFinished === insights.length) {
                    const payload: TimeToSeeDataPayload = {
                        type: 'dashboard_load',
                        context: 'dashboard',
                        action,
                        dashboard_query_id: dashboardQueryId,
                        api_response_bytes: totalResponseBytes,
                        time_to_see_data_ms: Math.floor(performance.now() - refreshStartTime),
                        insights_fetched: insights.length,
                        insights_fetched_cached: 0,
                    }
                    captureTimeToSeeData(values.currentTeamId, payload)
                    if (initialLoad) {
                        const { dashboardQueryId, startTime, responseBytes } = values.dashboardLoadTimerData
                        captureTimeToSeeData(values.currentTeamId, {
                            ...payload,
                            dashboard_query_id: dashboardQueryId,
                            action: 'initial_load_full',
                            time_to_see_data_ms: Math.floor(performance.now() - startTime),
                            api_response_bytes: responseBytes + totalResponseBytes,
                        })
                    }
                }
            })

            // run 4 item reloaders in parallel
            function loadNextPromise(): void {
                if (!breakpointTriggered && fetchItemFunctions.length > 0) {
                    fetchItemFunctions.shift()?.().then(loadNextPromise)
                }
            }

            for (let i = 0; i < 4; i++) {
                void loadNextPromise()
            }

            eventUsageLogic.actions.reportDashboardRefreshed(dashboardId, values.lastRefreshed)
        },
        updateAndRefreshDashboard: async (_, breakpoint) => {
            await breakpoint(200)
            await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                filters: values.filters,
                no_items_field: true,
            })
            actions.loadDashboardItems({ action: 'update_filters' })
        },
        setDates: ({ dateFrom, dateTo, reloadDashboard }) => {
            if (reloadDashboard) {
                actions.updateAndRefreshDashboard()
            }
            eventUsageLogic.actions.reportDashboardDateRangeChanged(dateFrom, dateTo)
        },
        setProperties: () => {
            actions.updateAndRefreshDashboard()
            eventUsageLogic.actions.reportDashboardPropertiesChanged()
        },
        setDashboardMode: async ({ mode, source }) => {
            // Edit mode special handling
            if (mode === DashboardMode.Fullscreen) {
                document.body.classList.add('fullscreen-scroll')
            } else {
                document.body.classList.remove('fullscreen-scroll')
            }
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
                cache.autoRefreshInterval = window.setInterval(() => {
                    actions.refreshAllDashboardItems({ action: 'refresh_automatic' })
                }, values.autoRefresh.interval * 1000)
            }
        },
        loadDashboardItemsSuccess: function (...args) {
            sharedListeners.reportLoadTiming(...args)

            const dashboard = values.allItems as DashboardType
            const { action, dashboardQueryId, startTime, responseBytes } = values.dashboardLoadTimerData
            const lastRefresh = sortDates(dashboard.tiles.map((tile) => tile.last_refresh))

            const initialLoad = action === 'initial_load'
            let allLoaded = true

            // Initial load of actual data for dashboard items after general dashboard is fetched
            if (
                values.lastRefreshed &&
                values.lastRefreshed.isBefore(now().subtract(AUTO_REFRESH_DASHBOARD_THRESHOLD_HOURS, 'hours'))
            ) {
                actions.refreshAllDashboardItems({ action: 'refresh_above_threshold', initialLoad, dashboardQueryId })
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
                dashboard_query_id: dashboardQueryId,
                time_to_see_data_ms: Math.floor(performance.now() - startTime),
                api_response_bytes: responseBytes,
                insights_fetched: dashboard.tiles.length,
                insights_fetched_cached: dashboard.tiles.reduce((acc, curr) => acc + (curr.is_cached ? 1 : 0), 0),
                min_last_refresh: lastRefresh[0],
                max_last_refresh: lastRefresh[lastRefresh.length - 1],
            }

            captureTimeToSeeData(values.currentTeamId, payload)
            if (initialLoad && allLoaded) {
                captureTimeToSeeData(values.currentTeamId, {
                    ...payload,
                    action: 'initial_load_full',
                })
            }

            if (values.shouldReportOnAPILoad) {
                actions.setShouldReportOnAPILoad(false)
                actions.reportDashboardViewed()
            }
        },
        reportDashboardViewed: async (_, breakpoint) => {
            // Caching `allItems`, as the dashboard might have unmounted after the breakpoint,
            // and "values.allItems" will then fail
            const { allItems, lastRefreshed } = values
            if (allItems) {
                eventUsageLogic.actions.reportDashboardViewed(allItems, lastRefreshed)
                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish
                if (
                    router.values.location.pathname === urls.dashboard(allItems.id) ||
                    router.values.location.pathname === urls.projectHomepage() ||
                    router.values.location.pathname.startsWith(urls.sharedDashboard(''))
                ) {
                    eventUsageLogic.actions.reportDashboardViewed(allItems, lastRefreshed, 10)
                }
            } else {
                // allItems has not loaded yet, report after API request is completed
                actions.setShouldReportOnAPILoad(true)
            }
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

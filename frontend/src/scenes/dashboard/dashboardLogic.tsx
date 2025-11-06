import {
    BindLogic,
    actions,
    connect,
    events,
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
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import uniqBy from 'lodash.uniqby'
import { Layout, Layouts } from 'react-grid-layout'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api, { ApiMethodOptions, getJSONOrNull } from 'lib/api'
import { DataColorTheme } from 'lib/colors'
import { OrganizationMembershipLevel } from 'lib/constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs, now } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { clearDOMTextSelection, getJSHeapMemory, shouldCancelQuery, toParams, uuid } from 'lib/utils'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { BREAKPOINTS } from 'scenes/dashboard/dashboardUtils'
import { calculateLayouts } from 'scenes/dashboard/tileLayouts'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { variableDataLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableDataLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'
import { getQueryBasedDashboard, getQueryBasedInsightModel } from '~/queries/nodes/InsightViz/utils'
import {
    BreakdownFilter,
    DashboardFilter,
    DataVisualizationNode,
    HogQLVariable,
    NodeKind,
    RefreshType,
} from '~/queries/schema/schema-general'
import {
    AccessControlLevel,
    AccessControlResourceType,
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
    ProjectTreeRef,
    QueryBasedInsightModel,
    TextModel,
} from '~/types'

import { getResponseBytes, sortDayJsDates } from '../insights/utils'
import { teamLogic } from '../teamLogic'
import { BreakdownColorConfig } from './DashboardInsightColorsModal'
import { TileFiltersOverride } from './TileFiltersOverride'
import type { dashboardLogicType } from './dashboardLogicType'
import {
    AUTO_REFRESH_INITIAL_INTERVAL_SECONDS,
    BREAKPOINT_COLUMN_COUNTS,
    DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES,
    IS_TEST_MODE,
    MAX_TILES_FOR_AUTOPREVIEW,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    combineDashboardFilters,
    encodeURLFilters,
    encodeURLVariables,
    getInsightWithRetry,
    layoutsByTile,
    parseURLFilters,
    parseURLVariables,
    runWithLimit,
} from './dashboardUtils'
import { tileLogic } from './tileLogic'

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
    error?: Error
    errored?: boolean
    timer?: Date | null
}

/**
 * Loading the dashboard serves two separate purposes:
 * 1. Fetching dashboard metadata (name, description, settings, etc.)
 * 2. Retrieving an initial cached version of its insights for fast display.
 */
export enum DashboardLoadAction {
    /** Initial dashboard load, when no variables are present. */
    InitialLoad = 'initial_load',
    /** Initial dashboard load, when variables are present in the URL. Deferred until variables are loaded. */
    InitialLoadWithVariables = 'initial_load_with_variables',
    /** Get a fresh copy of the dashboard after it was updated (e.g. a tile was duplicated or removed). */
    Update = 'update',
}

export enum RefreshDashboardItemsAction {
    /** Automatic or manual refresh of the dashboard. */
    Refresh = 'refresh',
    /** Refresh to apply temporary filters and variables. */
    Preview = 'preview',
}

// to stop kea typegen getting confused
export type DashboardTileLayoutUpdatePayload = Pick<DashboardTile, 'id' | 'layouts'>

export const dashboardLogic = kea<dashboardLogicType>([
    path(['scenes', 'dashboard', 'dashboardLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            featureFlagLogic,
            ['featureFlags'],
            variableDataLogic,
            ['variables'],
            dataThemeLogic,
            ['getTheme'],
        ],
        logic: [dashboardsModel, insightsModel, eventUsageLogic],
    })),

    props({} as DashboardLogicProps),

    key((props) => {
        if (typeof props.id !== 'number') {
            throw Error('Must init dashboardLogic with a numeric ID key')
        }
        return props.id
    }),

    actions(() => ({
        /**
         * Dashboard loading and dashboard tile refreshes.
         */
        loadDashboard: (payload: { action: DashboardLoadAction }) => payload,
        /** Load dashboard with streaming tiles approach. */
        loadDashboardStreaming: (payload: { action: DashboardLoadAction; manualDashboardRefresh?: boolean }) => payload,
        /** Dashboard metadata loaded successfully. */
        loadDashboardMetadataSuccess: (dashboard: DashboardType<QueryBasedInsightModel> | null) => ({ dashboard }),
        /** Single tile received from stream. */
        receiveTileFromStream: (data: { tile: any; order: number }) => data,
        /** Tile streaming completed. */
        tileStreamingComplete: true,
        /** Tile streaming failed. */
        tileStreamingFailure: (error: any) => ({ error }),
        /** Expose additional information about the current dashboard load in dashboardLoadData. */
        loadingDashboardItemsStarted: (action: DashboardLoadAction) => ({ action }),
        /** Expose response size information about the current dashboard load in dashboardLoadData. */
        setInitialLoadResponseBytes: (responseBytes: number) => ({ responseBytes }),
        /** Manually refresh the entire dashboard. */
        triggerDashboardRefresh: true,
        /** Manually refresh a single insight from the insight card on the dashboard. */
        refreshDashboardItem: (payload: { tile: DashboardTile<QueryBasedInsightModel> }) => payload,
        /** Refresh tiles of a loaded dashboard e.g. stale tiles after initial load, previewed tiles after applying filters, etc. */
        refreshDashboardItems: (payload: {
            action: RefreshDashboardItemsAction | DashboardLoadAction
            forceRefresh?: boolean
        }) => payload,
        /** Update a single refresh status. */
        setRefreshStatus: (shortId: InsightShortId, loading = false, queued = false) => ({ shortId, loading, queued }),
        /** Update multiple refresh statuses. */
        setRefreshStatuses: (shortIds: InsightShortId[], loading = false, queued = false) => ({
            shortIds,
            loading,
            queued,
        }),
        setRefreshError: (shortId: InsightShortId, error?: Error) => ({ shortId, error }),
        abortQuery: (payload: { queryId: string; queryStartTime: number }) => payload,
        abortAnyRunningQuery: true,

        /**
         * Auto-refresh while on page.
         **/
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        resetInterval: true,

        /*
         * Dashboard filters & variables.
         */
        setDates: (date_from: string | null, date_to: string | null) => ({
            date_from,
            date_to,
        }),
        setProperties: (properties: AnyPropertyFilter[] | null) => ({ properties }),
        setBreakdownFilter: (breakdown_filter: BreakdownFilter | null) => ({ breakdown_filter }),
        saveEditModeChanges: () => true,
        resetUrlFilters: () => true,
        resetIntermittentFilters: () => true,
        applyFilters: true,
        resetUrlVariables: true,
        setInitialVariablesLoaded: (initialVariablesLoaded: boolean) => ({ initialVariablesLoaded }),
        updateDashboardLastRefresh: (lastDashboardRefresh: Dayjs) => ({ lastDashboardRefresh }),
        overrideVariableValue: (variableId: string, value: any, isNull: boolean) => ({
            variableId,
            value,
            isNull,
        }),

        /**
         * Dashboard state.
         */
        setAccessDeniedToDashboard: true,
        /** Update the dashboard in dashboardsModel with given payload. */
        triggerDashboardUpdate: (payload) => ({ payload }),
        /** Update page visibility for virtualized rendering. */
        setPageVisibility: (visible: boolean) => ({ visible }),
        setSubscriptionMode: (enabled: boolean, id?: number | 'new') => ({ enabled, id }),
        /** Set the dashboard mode, see DashboardMode for details. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource | null) => ({ mode, source }),

        /**
         * Dashboard layout & tiles.
         */
        updateLayouts: (layouts: Layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        updateTileColor: (tileId: number, color: string | null) => ({ tileId, color }),
        duplicateTile: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),
        removeTile: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),
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
        setTileOverride: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),

        /**
         * Usage tracking.
         */
        setShouldReportOnAPILoad: (shouldReport: boolean) => ({ shouldReport }), // See reducer for details
        reportDashboardViewed: true, // Reports `viewed dashboard` and `dashboard analyzed` events
        reportInsightsViewed: (insights: QueryBasedInsightModel[]) => ({ insights }),

        /**
         * Dashboard result colors.
         */
        setBreakdownColorConfig: (config: BreakdownColorConfig) => ({ config }),
        setDataColorThemeId: (dataColorThemeId: number | null) => ({ dataColorThemeId }),

        setLoadLayoutFromServerOnPreview: (loadLayoutFromServerOnPreview: boolean) => ({
            loadLayoutFromServerOnPreview,
        }),
        dashboardNotFound: true,
    })),

    loaders(({ actions, props, values }) => ({
        dashboard: [
            null as DashboardType<QueryBasedInsightModel> | null,
            {
                loadDashboard: async ({ action }, breakpoint) => {
                    actions.loadingDashboardItemsStarted(action)

                    await breakpoint(200)

                    try {
                        const apiUrl = values.apiUrl('force_cache', values.urlFilters, values.urlVariables)
                        const dashboardResponse: Response = await api.getResponse(apiUrl)
                        const dashboard: DashboardType<InsightModel> | null = await getJSONOrNull(dashboardResponse)

                        actions.setInitialLoadResponseBytes(getResponseBytes(dashboardResponse))

                        return getQueryBasedDashboard(dashboard)
                    } catch (error: any) {
                        if (error.status === 404) {
                            return null
                        }
                        if (error.status === 403 && error.code === 'permission_denied') {
                            actions.setAccessDeniedToDashboard()
                        }
                        throw error
                    }
                },
                loadDashboardStreaming: async ({ action }, breakpoint) => {
                    actions.loadingDashboardItemsStarted(action)
                    await breakpoint(200)
                    actions.resetIntermittentFilters()

                    // Start unified streaming - metadata followed by tiles
                    api.dashboards.streamTiles(
                        props.id,
                        {
                            layoutSize: values.currentLayoutSize,
                            filtersOverride: values.urlFilters,
                            variablesOverride: values.urlVariables,
                        },
                        // onMessage callback - handles both metadata and tiles
                        (data) => {
                            if (data.type === 'metadata') {
                                actions.loadDashboardMetadataSuccess(
                                    getQueryBasedDashboard(data.dashboard as DashboardType<InsightModel>)
                                )
                            } else if (data.type === 'tile') {
                                actions.receiveTileFromStream(data)
                            }
                        },
                        // onComplete callback
                        () => {
                            actions.tileStreamingComplete()
                        },
                        // onError callback
                        (error) => {
                            console.error('❌ Tile streaming error:', error)
                            actions.tileStreamingFailure(error)
                        }
                    )

                    // Return null - metadata will update the dashboard
                    return null
                },
                saveEditModeChanges: async (_, breakpoint) => {
                    actions.abortAnyRunningQuery()

                    try {
                        const layoutsToUpdate = (values.dashboard?.tiles || []).map((tile) => ({
                            id: tile.id,
                            layouts: tile.layouts,
                        }))

                        breakpoint()

                        const dashboard: DashboardType<InsightModel> = await api.update(
                            `api/environments/${values.currentTeamId}/dashboards/${props.id}`,
                            {
                                filters: values.effectiveEditBarFilters,
                                variables: values.effectiveDashboardVariableOverrides,
                                breakdown_colors: values.temporaryBreakdownColors,
                                data_color_theme_id: values.dataColorThemeId,
                                tiles: layoutsToUpdate,
                            }
                        )
                        actions.resetUrlFilters()
                        actions.resetUrlVariables()
                        return getQueryBasedDashboard(dashboard)
                    } catch (e) {
                        lemonToast.error('Could not update dashboard: ' + String(e))
                        return values.dashboard
                    }
                },
                updateTileColor: async ({ tileId, color }) => {
                    await api.update(`api/environments/${values.currentTeamId}/dashboards/${props.id}`, {
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
                        await api.update(`api/environments/${values.currentTeamId}/dashboards/${props.id}`, {
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
                        if (newTile.text) {
                            newTile.text = { body: newTile.text.body } as TextModel
                        }

                        const dashboard: DashboardType<InsightModel> = await api.update(
                            `api/environments/${values.currentTeamId}/dashboards/${props.id}`,
                            {
                                duplicate_tiles: [newTile],
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
                        `api/environments/${teamLogic.values.currentTeamId}/dashboards/${props.id}/move_tile`,
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
        dashboardLoading: [
            false,
            {
                loadDashboard: () => true,
                loadDashboardSuccess: () => false,
                loadDashboardFailure: () => false,
            },
        ],
        dashboardStreaming: [
            false,
            {
                loadDashboardStreaming: () => true,
                tileStreamingComplete: () => false,
                tileStreamingFailure: () => false,
            },
        ],
        loadingPreview: [
            false,
            {
                setDates: () => false,
                setProperties: () => false,
                setBreakdownFilter: () => false,
                loadDashboardSuccess: () => false,
                loadDashboardFailure: () => false,
                applyFilters: () => true,
            },
        ],
        cancellingPreview: [
            false,
            {
                // have to reload dashboard when when cancelling preview
                // and resetting filters
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
        accessDeniedToDashboard: [
            false,
            {
                setAccessDeniedToDashboard: () => true,
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
                loadDashboardSuccess: (_, { dashboard }) => {
                    const tileIdToLayouts: Record<number, DashboardTile['layouts']> = {}
                    dashboard?.tiles.forEach((tile: DashboardTile<QueryBasedInsightModel>) => {
                        tileIdToLayouts[tile.id] = tile.layouts
                    })

                    return tileIdToLayouts
                },
            },
        ],
        temporaryBreakdownColors: [
            [] as BreakdownColorConfig[],
            {
                setBreakdownColorConfig: (state, { config }) => {
                    const existingConfigIndex = state.findIndex((c) => c.breakdownValue === config.breakdownValue)
                    if (existingConfigIndex >= 0) {
                        return [...state.slice(0, existingConfigIndex), config, ...state.slice(existingConfigIndex + 1)]
                    }
                    return [...state, config]
                },
                loadDashboardSuccess: (state, { dashboard }) => {
                    return [...state, ...(dashboard?.breakdown_colors ?? [])]
                },
            },
        ],
        dataColorThemeId: [
            null as number | null,
            {
                setDataColorThemeId: (_, { dataColorThemeId }) => dataColorThemeId || null,
                loadDashboardSuccess: (_, { dashboard }) => dashboard?.data_color_theme_id || null,
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
                loadDashboardMetadataSuccess: (state, { dashboard }) => {
                    if (!dashboard) {
                        return state
                    }
                    return dashboard
                },
                receiveTileFromStream: (state, { tile }) => {
                    if (!state || !state.tiles) {
                        return state
                    }

                    const transformedTile = {
                        ...tile,
                        ...(tile.insight != null ? { insight: getQueryBasedInsightModel(tile.insight) } : {}),
                    }

                    let newTiles = [...state.tiles, transformedTile]

                    return {
                        ...state,
                        tiles: newTiles,
                    } as DashboardType<QueryBasedInsightModel>
                },
            },
        ],
        loadTimer: [null as Date | null, { loadDashboard: () => new Date(), loadDashboardStreaming: () => new Date() }],
        dashboardLoadData: [
            {
                action: undefined,
                dashboardQueryId: '',
                startTime: 0,
                responseBytes: 0,
            } as {
                action: DashboardLoadAction | undefined
                dashboardQueryId: string
                startTime: number
                responseBytes: number
            },
            {
                loadingDashboardItemsStarted: (_, { action }) => ({
                    action,
                    dashboardQueryId: uuid(), // generate new query id for the refresh
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
                setRefreshError: (state, { shortId, error }) => ({
                    ...state,
                    [shortId]: { errored: true, error, timer: state[shortId]?.timer || null },
                }),
                refreshDashboardItems: () => ({}),
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
        loadLayoutFromServerOnPreview: [
            false,
            {
                setLoadLayoutFromServerOnPreview: (_, { loadLayoutFromServerOnPreview }) =>
                    loadLayoutFromServerOnPreview,
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

        lastDashboardRefresh: [
            null as Dayjs | null,
            {
                loadDashboardSuccess: (_, { dashboard }) => {
                    return dashboard?.last_refresh ? dayjs(dashboard.last_refresh) : null
                },
                loadDashboardMetadataSuccess: (_, { dashboard }) => {
                    return dashboard?.last_refresh ? dayjs(dashboard.last_refresh) : null
                },
                updateDashboardLastRefresh: (_, { lastDashboardRefresh }) => lastDashboardRefresh,
            },
        ],
        error404: [
            false,
            {
                dashboardNotFound: () => true,
                loadDashboardSuccess: () => false,
                loadDashboardFailure: () => false,
            },
        ],
        /** Dashboard variables */
        initialVariablesLoaded: [
            false,
            {
                setInitialVariablesLoaded: (_, { initialVariablesLoaded }) => initialVariablesLoaded,
            },
        ],
        intermittentFilters: [
            {
                date_from: undefined,
                date_to: undefined,
                properties: undefined,
                breakdown_filter: undefined,
            } as DashboardFilter,
            {
                setDates: (state, { date_from, date_to }) => ({
                    ...state,
                    date_from,
                    date_to,
                }),
                setProperties: (state, { properties }) => ({
                    ...state,
                    properties,
                }),
                setBreakdownFilter: (state, { breakdown_filter }) => ({
                    ...state,
                    breakdown_filter,
                }),
                resetIntermittentFilters: () => ({
                    date_from: undefined,
                    date_to: undefined,
                    properties: undefined,
                    breakdown_filter: undefined,
                }),
            },
        ],
    })),
    selectors(() => ({
        shouldUseStreaming: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => {
                const hasFeatureFlag = !!featureFlags[FEATURE_FLAGS.SSE_DASHBOARDS]
                const hasSSESupport = typeof EventSource !== 'undefined'
                return hasFeatureFlag && hasSSESupport
            },
        ],
        canAutoPreview: [
            (s) => [s.dashboard],
            (dashboard) => (dashboard?.tiles.length || 0) < MAX_TILES_FOR_AUTOPREVIEW,
        ],
        hasIntermittentFilters: [
            (s) => [s.intermittentFilters],
            (intermittentFilters) => Object.values(intermittentFilters).some((filter) => filter !== undefined),
        ],
        hasUrlFilters: [
            (s) => [s.urlFilters],
            (urlFilters) => Object.values(urlFilters).some((filter) => filter !== undefined),
        ],
        showEditBarApplyPopover: [
            (s) => [s.canAutoPreview, s.hasIntermittentFilters],
            (canAutoPreview, hasIntermittentFilters) => !canAutoPreview && hasIntermittentFilters,
        ],
        urlFilters: [() => [router.selectors.searchParams], (searchParams) => parseURLFilters(searchParams)],
        effectiveEditBarFilters: [
            (s) => [s.dashboard, s.urlFilters, s.intermittentFilters],
            (dashboard, urlFilters, intermittentFilters) => {
                const effectiveEditBarFilters = combineDashboardFilters(
                    dashboard?.persisted_filters || {},
                    urlFilters,
                    intermittentFilters
                )
                return effectiveEditBarFilters
            },
        ],
        effectiveDashboardVariableOverrides: [
            (s) => [s.dashboard, s.urlVariables],
            (dashboard, urlVariables) => ({ ...dashboard?.persisted_variables, ...urlVariables }),
        ],
        effectiveVariablesAndAssociatedInsights: [
            (s) => [s.dashboard, s.variables, s.urlVariables],
            (
                dashboard: DashboardType,
                variables: Variable[],
                urlVariables: Record<string, HogQLVariable>
            ): { variable: Variable; insightNames: string[] }[] => {
                const dataVizNodes = (dashboard?.tiles ?? [])
                    .map((n) => ({ query: n.insight?.query, title: n.insight?.name }))
                    .filter((n) => n.query?.kind === NodeKind.DataVisualizationNode)
                    .filter(
                        (n): n is { query: DataVisualizationNode; title: string } =>
                            Boolean(n.query) && Boolean(n.title)
                    )

                const usedVariables = dataVizNodes
                    .map((n) => n.query.source.variables)
                    .filter((n): n is Record<string, HogQLVariable> => Boolean(n))
                    .flatMap((n) => Object.values(n))
                const uniqueVariables = uniqBy(usedVariables, (n) => n.variableId)

                const effectiveVariables = uniqueVariables
                    .map((v) => {
                        const variable = variables.find((n) => n.id === v.variableId)
                        const urlVariable = urlVariables[v.variableId]

                        if (!variable) {
                            return null
                        }

                        const urlValueOverride = urlVariable?.value
                        const dashboardValueOverride = dashboard.persisted_variables?.[v.variableId]?.value
                        const insightValueOverride = v.value
                        const defaultVariableValue = variable.default_value

                        const urlIsNullOverride = urlVariable?.isNull
                        const dashboardIsNullOverride = dashboard.persisted_variables?.[v.variableId]?.isNull
                        const insightIsNullOverride = v.isNull
                        const defaultVariableIsNull = variable.isNull

                        // determine effective variable state
                        const resultVar: Variable = {
                            ...variable,
                            value:
                                urlValueOverride ||
                                dashboardValueOverride ||
                                insightValueOverride ||
                                defaultVariableValue,
                            isNull:
                                urlIsNullOverride ||
                                dashboardIsNullOverride ||
                                insightIsNullOverride ||
                                defaultVariableIsNull,
                        }

                        // get insights using variable
                        const insightsUsingVariable = dataVizNodes
                            .filter((n) => {
                                const vars = n.query.source.variables
                                if (!vars) {
                                    return false
                                }

                                return !!vars[v.variableId]
                            })
                            .map((n) => n.title)

                        return { variable: resultVar, insightNames: insightsUsingVariable }
                    })
                    .filter((n): n is { variable: Variable; insightNames: string[] } => Boolean(n?.variable))

                return effectiveVariables
            },
        ],
        urlVariables: [
            (s) => [router.selectors.searchParams, s.variables, s.initialVariablesLoaded],
            (searchParams, variables, initialVariablesLoaded): Record<string, HogQLVariable> => {
                if (!initialVariablesLoaded) {
                    // if initial variables are not loaded yet, we can't map the variables in the url
                    return {}
                }

                // try to convert url variables to variables
                const urlVariablesRaw = parseURLVariables(searchParams)
                const urlVariables: Record<string, HogQLVariable> = {}

                for (const [key, value] of Object.entries(urlVariablesRaw)) {
                    const variable = variables.find((variable: Variable) => variable.code_name === key)
                    if (variable) {
                        urlVariables[variable.id] = {
                            code_name: variable.code_name,
                            variableId: variable.id,
                            value,
                            isNull: value === null,
                        }
                    }
                }

                return urlVariables
            },
        ],
        hasVariables: [
            (s) => [s.effectiveVariablesAndAssociatedInsights],
            (effectiveVariablesAndAssociatedInsights) =>
                Object.keys(effectiveVariablesAndAssociatedInsights).length > 0,
        ],
        asDashboardTemplate: [
            (s) => [s.dashboard],
            (dashboard: DashboardType): DashboardTemplateEditorType | undefined => {
                return dashboard
                    ? {
                          template_name: dashboard.name,
                          dashboard_description: dashboard.description,
                          dashboard_filters: dashboard.filters,
                          tags: dashboard.tags || [],
                          tiles: dashboard.tiles
                              .filter((tile) => !tile.error) // Skip error tiles when creating templates
                              .map((tile) => {
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
            (_, p) => [p.id],
            (id) => {
                return (
                    refresh?: RefreshType,
                    filtersOverride?: DashboardFilter,
                    variablesOverride?: Record<string, HogQLVariable>,
                    layoutSize?: 'sm' | 'xs'
                ) =>
                    `api/environments/${teamLogic.values.currentTeamId}/dashboards/${id}/?${toParams({
                        refresh,
                        filters_override: filtersOverride,
                        variables_override: variablesOverride,
                        layout_size: layoutSize,
                    })}`
            },
        ],
        currentLayoutSize: [
            (s) => [s.containerWidth],
            (containerWidth): 'sm' | 'xs' => {
                // Use precise container width when available, otherwise estimate from window width
                if (containerWidth !== null) {
                    return containerWidth > BREAKPOINTS.sm ? 'sm' : 'xs'
                }
                // Estimate from window width, accounting for ~300px of sidebars
                const windowWidth = typeof window !== 'undefined' ? window.innerWidth : 1200
                const estimatedContainerWidth = windowWidth - 300
                return estimatedContainerWidth > BREAKPOINTS.sm ? 'sm' : 'xs'
            },
        ],
        tiles: [(s) => [s.dashboard], (dashboard) => dashboard?.tiles?.filter((t) => !t.deleted) || []],
        insightTiles: [
            (s) => [s.tiles],
            (tiles) => tiles.filter((t) => !!t.insight).filter((i) => !i.insight?.deleted),
        ],
        textTiles: [(s) => [s.tiles], (tiles) => tiles.filter((t) => !!t.text)],
        itemsLoading: [
            (s) => [s.dashboardLoading, s.dashboardStreaming, s.refreshStatus, s.initialVariablesLoaded],
            (dashboardLoading, dashboardStreaming, refreshStatus, initialVariablesLoaded) => {
                return (
                    dashboardLoading ||
                    dashboardStreaming ||
                    Object.values(refreshStatus).some((s) => s.loading || s.queued) ||
                    (SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams && !initialVariablesLoaded)
                )
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
        oldestRefreshed: [
            // selecting page visibility to update the refresh when a page comes back into view
            (s) => [s.sortedDates, s.pageVisibility],
            (sortedDates): Dayjs | null => {
                if (!sortedDates.length) {
                    return null
                }

                return sortedDates[0]
            },
        ],
        effectiveLastRefresh: [
            (s) => [s.lastDashboardRefresh, s.oldestRefreshed],
            (lastDashboardRefresh, oldestRefreshed): Dayjs | null => {
                const dates = [lastDashboardRefresh, oldestRefreshed].filter((d): d is Dayjs => d != null)
                return sortDayJsDates(dates)[dates.length - 1]
            },
        ],

        nextAllowedDashboardRefresh: [
            (s) => [s.lastDashboardRefresh],
            (lastDashboardRefresh): Dayjs | null => {
                if (!lastDashboardRefresh) {
                    return null
                }

                return lastDashboardRefresh.add(DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES, 'minutes')
            },
        ],
        blockRefresh: [
            // page visibility is only here to trigger a recompute when the page is hidden/shown
            (s) => [s.nextAllowedDashboardRefresh, s.placement, s.pageVisibility],
            (nextAllowedDashboardRefresh: Dayjs, placement: DashboardPlacement) => {
                return (
                    !(placement === DashboardPlacement.FeatureFlag) &&
                    !(placement === DashboardPlacement.Group) &&
                    !!nextAllowedDashboardRefresh &&
                    nextAllowedDashboardRefresh?.isAfter(now())
                )
            },
        ],
        canEditDashboard: [
            (s) => [s.dashboard],
            (dashboard) => {
                return dashboard?.user_access_level
                    ? accessLevelSatisfied(
                          AccessControlResourceType.Dashboard,
                          dashboard.user_access_level,
                          AccessControlLevel.Editor
                      )
                    : false
            },
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
            (s) => [s.dashboard, s.error404, s.dashboardFailedToLoad],
            (dashboard, error404, dashboardFailedToLoad): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Dashboards,
                        name: 'Dashboards',
                        path: urls.dashboards(),
                        iconType: 'dashboard',
                    },
                    {
                        key: [Scene.Dashboard, dashboard?.id || 'new'],
                        name: dashboard?.id
                            ? dashboard.name
                            : dashboardFailedToLoad
                              ? 'Could not load'
                              : error404
                                ? 'Not found'
                                : '...',
                        iconType: 'dashboard',
                    },
                ]
            },
        ],
        projectTreeRef: [
            () => [(_, props: DashboardLogicProps) => props.id],
            (id): ProjectTreeRef => {
                return { type: 'dashboard', ref: String(id) }
            },
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
        dataColorTheme: [
            (s) => [s.dataColorThemeId, s.getTheme],
            (dataColorThemeId, getTheme): DataColorTheme | null => getTheme(dataColorThemeId),
        ],
        maxContext: [
            (s) => [s.dashboard],
            (dashboard): MaxContextInput[] => {
                if (!dashboard) {
                    return []
                }

                return [createMaxContextHelpers.dashboard(dashboard)]
            },
        ],
    })),
    events(({ actions, props, values }) => ({
        afterMount: () => {
            // NOTE: initial dashboard load is done after variables are loaded in initialVariablesLoaded
            if (props.id) {
                if (props.dashboard) {
                    // If we already have dashboard data, use it. Should the data turn out to be stale,
                    // the loadDashboardSuccess listener will initiate a refresh
                    // Ensure loading state is properly initialized for shared dashboards
                    actions.loadingDashboardItemsStarted(DashboardLoadAction.InitialLoad)
                    actions.loadDashboardSuccess(props.dashboard)
                } else {
                    if (!(SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams)) {
                        if (values.shouldUseStreaming) {
                            // Streaming loading: load metadata + stream tiles
                            actions.loadDashboardStreaming({
                                action: DashboardLoadAction.InitialLoad,
                            })
                        } else {
                            // Regular loading
                            actions.loadDashboard({
                                action: DashboardLoadAction.InitialLoad,
                            })
                        }
                    }
                }
            }
        },
        beforeUnmount: () => {
            actions.abortAnyRunningQuery()
        },
    })),
    sharedListeners(({ values, props, actions }) => ({
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
        handleDashboardLoadComplete: () => {
            // Shared logic for refreshing dashboard items after load (used by both regular and streaming loads)
            if (values.placement !== DashboardPlacement.Export) {
                // access stored values from dashboardLoadData
                // as we can't pass them down to this listener
                const loadAction = values.dashboardLoadData.action!
                actions.refreshDashboardItems({ action: loadAction, forceRefresh: false })
            }

            if (values.shouldReportOnAPILoad) {
                actions.setShouldReportOnAPILoad(false)
                actions.reportDashboardViewed()
            }
        },
    })),
    listeners(({ actions, values, cache, props, sharedListeners }) => ({
        setRefreshError: sharedListeners.reportRefreshTiming,
        setRefreshStatuses: sharedListeners.reportRefreshTiming,
        setRefreshStatus: sharedListeners.reportRefreshTiming,
        loadDashboardFailure: () => {
            const { action, dashboardQueryId, startTime } = values.dashboardLoadData

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
        tileStreamingFailure: ({ error }) => {
            if (error?.message?.includes('404') || error?.status === 404) {
                actions.dashboardNotFound()
            } else if (error?.message?.includes('403') || error?.status === 403) {
                actions.setAccessDeniedToDashboard()
            } else {
                // Show error toast for other errors (500s, network issues, etc.)
                const errorMessage = error?.message || 'Dashboard streaming failed'
                lemonToast.error(`Failed to load dashboard: ${errorMessage}`)
            }
        },

        [insightsModel.actionTypes.duplicateInsightSuccess]: () => {
            // TODO this is a bit hacky, but we need to reload the dashboard to get the new insight
            // TODO when duplicated from a dashboard we should carry the context so only one logic needs to reload
            // TODO or we should duplicate the tile (and implicitly the insight)
            actions.loadDashboard({ action: DashboardLoadAction.Update })
        },
        [dashboardsModel.actionTypes.tileAddedToDashboard]: ({ dashboardId }) => {
            // when adding an insight to a dashboard, we need to reload the dashboard to get the new insight
            if (dashboardId === props.id) {
                actions.loadDashboard({ action: DashboardLoadAction.Update })
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
                actions.loadDashboard({ action: DashboardLoadAction.Update })
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
        /** Triggered from dashboard refresh button, when user refreshes entire dashboard */
        triggerDashboardRefresh: () => {
            // reset auto refresh interval
            actions.resetInterval()
            actions.refreshDashboardItems({ action: RefreshDashboardItemsAction.Refresh, forceRefresh: true })
        },
        /** Called when a single insight is refreshed manually on the dashboard */
        refreshDashboardItem: async ({ tile }, breakpoint) => {
            const dashboardId: number = props.id
            const insight = tile.insight

            if (!insight) {
                return
            }

            actions.setRefreshStatus(insight.short_id, true, true)

            try {
                breakpoint()

                const refreshStartTime = performance.now()
                // when one insight is refreshed manually, we want to avoid cache and force a refresh of the insight
                // hence using 'force_blocking', small cost to give latest data for the insight
                // also it's then consistent with the dashboard refresh button
                const refreshedInsight = await getInsightWithRetry(
                    values.currentTeamId,
                    insight,
                    dashboardId,
                    uuid(),
                    'force_blocking',
                    undefined,
                    values.urlFilters,
                    values.urlVariables,
                    tile.filters_overrides
                )

                eventUsageLogic.actions.reportDashboardTileRefreshed(
                    dashboardId,
                    tile,
                    values.urlFilters,
                    values.urlVariables,
                    Math.floor(performance.now() - refreshStartTime),
                    true
                )

                if (refreshedInsight) {
                    dashboardsModel.actions.updateDashboardInsight(refreshedInsight)
                    actions.setRefreshStatus(insight.short_id)
                } else {
                    actions.setRefreshError(insight.short_id)
                }
            } catch (e: any) {
                actions.setRefreshError(insight.short_id, e)
            }
        },
        refreshDashboardItems: async ({ action, forceRefresh }, breakpoint) => {
            const dashboardRefreshStartTime = performance.now()
            const isInitialLoad =
                action === DashboardLoadAction.InitialLoad || action === DashboardLoadAction.InitialLoadWithVariables
            const isInitialLoadOrUpdate = isInitialLoad || action === DashboardLoadAction.Update

            const dashboardId: number = props.id
            const allInsightTiles = values.insightTiles || []
            const totalTileCount = allInsightTiles.length

            const sortedTilesToRefresh = allInsightTiles
                // sort tiles so we poll them in the exact order they are computed on the backend
                .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
                .filter(
                    (t): t is DashboardTile<QueryBasedInsightModel> & { insight: QueryBasedInsightModel } => !!t.insight
                )
                // only refresh stale insights
                .filter(
                    (t) =>
                        forceRefresh ||
                        !isInitialLoadOrUpdate ||
                        !t.insight.cache_target_age ||
                        dayjs(t.insight.cache_target_age).isBefore(dayjs())
                )

            const tilesStaleCount = sortedTilesToRefresh.length
            let tilesRefreshedCount = 0
            let tilesErroredCount = 0
            let tilesAbortedCount = 0

            if (sortedTilesToRefresh.length > 0) {
                await breakpoint()
                actions.resetIntermittentFilters()

                // Set refresh status for all insights
                actions.setRefreshStatuses(
                    sortedTilesToRefresh.map((tile) => tile.insight.short_id),
                    false,
                    true
                )

                actions.abortAnyRunningQuery()
                cache.abortController = new AbortController()
                const methodOptions: ApiMethodOptions = { signal: cache.abortController.signal }

                const fetchSyncInsightFunctions = sortedTilesToRefresh.map((tile) => async () => {
                    const insight = tile.insight
                    const queryId = uuid()
                    const queryStartTime = performance.now()
                    const dashboardId: number = props.id

                    // Set insight as refreshing
                    actions.setRefreshStatus(insight.short_id, true, true)

                    try {
                        const insightRefreshStartTime = performance.now()
                        const refreshedInsight = await getInsightWithRetry(
                            values.currentTeamId,
                            insight,
                            dashboardId,
                            queryId,
                            forceRefresh ? 'force_blocking' : 'blocking', // 'blocking' returns cached data if available, when manual refresh is triggered we want fresh results
                            methodOptions,
                            values.urlFilters,
                            values.urlVariables,
                            tile.filters_overrides
                        )

                        if (refreshedInsight) {
                            dashboardsModel.actions.updateDashboardInsight(refreshedInsight)
                            actions.setRefreshStatus(insight.short_id)
                            tilesRefreshedCount++

                            eventUsageLogic.actions.reportDashboardTileRefreshed(
                                dashboardId,
                                tile,
                                values.urlFilters,
                                values.urlVariables,
                                Math.floor(performance.now() - insightRefreshStartTime),
                                false
                            )
                        } else {
                            actions.setRefreshError(insight.short_id)
                            tilesErroredCount++
                        }
                    } catch (e: any) {
                        if (shouldCancelQuery(e)) {
                            console.warn(`Insight refresh cancelled for ${insight.short_id} due to abort signal:`, e)
                            actions.abortQuery({ queryId, queryStartTime })
                            tilesAbortedCount++
                        } else {
                            actions.setRefreshError(insight.short_id, e)
                            tilesErroredCount++
                        }
                    }
                })

                // Execute the fetches with concurrency limit of 4
                await runWithLimit(fetchSyncInsightFunctions, 4)
                breakpoint()

                // REFRESH DONE: all insights have been refreshed

                // update last refresh time, only if we've forced a blocking refresh of the dashboard
                if (forceRefresh) {
                    actions.updateDashboardLastRefresh(dayjs())
                }

                if (isInitialLoad) {
                    // capture time to see data
                    const { dashboardQueryId, startTime, responseBytes } = values.dashboardLoadData
                    eventUsageLogic.actions.reportTimeToSeeData({
                        team_id: values.currentTeamId,
                        type: 'dashboard_load',
                        context: 'dashboard',
                        action,
                        status: 'success',
                        primary_interaction_id: dashboardQueryId,
                        time_to_see_data_ms: Math.floor(performance.now() - startTime),
                        api_response_bytes: responseBytes,
                        insights_fetched: sortedTilesToRefresh.length,
                        insights_fetched_cached: values.dashboard?.tiles.reduce(
                            (acc, curr) => acc + (curr.is_cached ? 1 : 0),
                            0
                        ),
                        ...getJSHeapMemory(),
                    })
                }

                eventUsageLogic.actions.reportDashboardRefreshed(
                    dashboardId,
                    values.dashboard,
                    values.urlFilters,
                    values.urlVariables,
                    values.lastDashboardRefresh,
                    action,
                    !!forceRefresh,
                    {
                        totalTileCount,
                        tilesStaleCount,
                        tilesRefreshedCount,
                        tilesErroredCount,
                        tilesAbortedCount,
                        refreshDurationMs: Math.floor(performance.now() - dashboardRefreshStartTime),
                    }
                )
            }
        },
        saveEditModeChanges: () => {
            if (
                values.dashboard?.persisted_filters?.date_from !== values.effectiveEditBarFilters.date_from ||
                values.dashboard?.persisted_filters?.date_to !== values.effectiveEditBarFilters.date_to
            ) {
                eventUsageLogic.actions.reportDashboardDateRangeChanged(
                    values.dashboard,
                    values.effectiveEditBarFilters.date_from,
                    values.effectiveEditBarFilters.date_to
                )
            }
            if (
                JSON.stringify(values.dashboard?.persisted_filters?.properties) !==
                JSON.stringify(values.effectiveEditBarFilters.properties)
            ) {
                eventUsageLogic.actions.reportDashboardPropertiesChanged(values.dashboard)
            }
        },
        setDashboardMode: async ({ mode, source }) => {
            if (mode === DashboardMode.Edit && source !== DashboardEventSource.DashboardHeaderDiscardChanges) {
                // Note: handled in subscriptions
            } else if (source === DashboardEventSource.DashboardHeaderDiscardChanges) {
                // cancel edit mode changesdashboardLogi

                // reset filters to that before previewing
                actions.resetIntermittentFilters()
                actions.resetUrlVariables()

                // reset tile data by reloading dashboard
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })

                // also reset layout to that we stored in dashboardLayouts
                // this is done in the reducer for dashboard
            } else if (mode === null && source === DashboardEventSource.DashboardHeaderOverridesBanner) {
                // discard overrides when opening a dashboard from a link with overrides

                // remove overrides from url
                actions.resetUrlFilters()
                actions.resetUrlVariables()

                // reset tile data by reloading dashboard
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Refresh,
                    forceRefresh: false,
                })
            } else if (
                mode === null &&
                (source === DashboardEventSource.DashboardHeaderSaveDashboard ||
                    (source === DashboardEventSource.Hotkey && values.dashboardMode === DashboardMode.Edit))
            ) {
                // save edit mode changes
                actions.saveEditModeChanges()
            }

            if (mode) {
                eventUsageLogic.actions.reportDashboardModeToggled(values.dashboard, mode, source)
            }
        },
        setAutoRefresh: () => {
            actions.resetInterval()
        },
        resetInterval: () => {
            if (values.autoRefresh.enabled) {
                // Refresh right now after enabling if we haven't refreshed recently
                if (
                    !values.itemsLoading &&
                    values.lastDashboardRefresh &&
                    values.lastDashboardRefresh.isBefore(now().subtract(values.autoRefresh.interval, 'seconds'))
                ) {
                    actions.refreshDashboardItems({
                        action: RefreshDashboardItemsAction.Refresh,
                        forceRefresh: true,
                    })
                }
                cache.disposables.add(() => {
                    const intervalId = window.setInterval(() => {
                        actions.refreshDashboardItems({
                            action: RefreshDashboardItemsAction.Refresh,
                            forceRefresh: true,
                        })
                    }, values.autoRefresh.interval * 1000)
                    return () => clearInterval(intervalId)
                }, 'autoRefreshInterval')
            }
        },
        loadDashboardSuccess: [
            sharedListeners.reportLoadTiming,
            () => {
                if (!values.dashboard) {
                    actions.dashboardNotFound()
                    return // We hit a 404
                }
            },
            sharedListeners.handleDashboardLoadComplete,
        ],
        loadDashboardMetadataSuccess: ({ dashboard }) => {
            if (!dashboard) {
                actions.dashboardNotFound()
                return // We hit a 404
            }
        },
        tileStreamingComplete: sharedListeners.handleDashboardLoadComplete,
        reportInsightsViewed: ({ insights }: { insights: QueryBasedInsightModel[] }) => {
            const insightIds = insights
                .map((insight: QueryBasedInsightModel) => insight?.id)
                .filter((id): id is number => !!id)

            if (insightIds.length > 0 && values.currentTeamId) {
                void api.create(`api/environments/${values.currentTeamId}/insights/viewed`, {
                    insight_ids: insightIds,
                })
            }
        },
        reportDashboardViewed: async (_, breakpoint) => {
            // Caching `dashboard`, as the dashboard might have unmounted after the breakpoint,
            // and "values.dashboard" will then fail
            const { dashboard, lastDashboardRefresh, tiles } = values
            if (dashboard) {
                eventUsageLogic.actions.reportDashboardViewed(dashboard, lastDashboardRefresh)

                const insights = tiles.map((t) => t.insight).filter((i): i is QueryBasedInsightModel => !!i)
                actions.reportInsightsViewed(insights)

                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish
                if (
                    router.values.location.pathname === urls.dashboard(dashboard.id) ||
                    router.values.location.pathname === urls.projectHomepage() ||
                    router.values.location.pathname.startsWith(urls.sharedDashboard(''))
                ) {
                    eventUsageLogic.actions.reportDashboardViewed(dashboard, lastDashboardRefresh, 10)
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
        abortQuery: async ({ queryId, queryStartTime }) => {
            const { currentTeamId } = values
            try {
                await api.insights.cancelQuery(queryId, currentTeamId ?? undefined)
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }

            const { dashboardQueryId } = values.dashboardLoadData
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
        applyFilters: () => {
            actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Preview,
                forceRefresh: false,
            })
        },
        setProperties: () => {
            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        setDates: () => {
            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        setBreakdownFilter: () => {
            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        overrideVariableValue: () => {
            actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Preview,
                forceRefresh: false,
            })
            actions.setDashboardMode(DashboardMode.Edit, null)
        },
        [variableDataLogic.actionTypes.getVariablesSuccess]: () => {
            // Only run this handler once on startup
            // This ensures variables are loaded before the dashboard is loaded and insights are refreshed
            if (values.initialVariablesLoaded) {
                return
            }

            if (SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams) {
                if (values.shouldUseStreaming) {
                    actions.loadDashboardStreaming({
                        action: DashboardLoadAction.InitialLoadWithVariables,
                    })
                } else {
                    actions.loadDashboard({
                        action: DashboardLoadAction.InitialLoadWithVariables,
                    })
                }
            }

            actions.setInitialVariablesLoaded(true)
        },
        updateDashboardLastRefresh: ({ lastDashboardRefresh }) => {
            dashboardsModel.actions.updateDashboard({
                id: props.id,
                last_refresh: lastDashboardRefresh.toISOString(),
                discardResult: true,
            })
        },
        setTileOverride: ({ tile }) => {
            const tileLogicProps = { dashboardId: props.id, tileId: tile.id, filtersOverrides: tile.filters_overrides }
            const logic = tileLogic(tileLogicProps)

            LemonDialog.openForm({
                title: 'Override Tile Filters',
                initialValues: {},
                content: (
                    <BindLogic logic={tileLogic} props={tileLogicProps}>
                        <TileFiltersOverride tile={tile} />
                    </BindLogic>
                ),
                tertiaryButton: {
                    children: 'Clear All Overrides',
                    onClick: () => {
                        logic.actions.resetOverrides()
                    },
                    preventClosing: true,
                },
                onSubmit: async () => {
                    const tileFilterOverrides = logic.values.overrides

                    await api.update(`api/environments/${teamLogic.values.currentTeamId}/dashboards/${props.id}`, {
                        tiles: [{ id: tile.id, filters_overrides: tileFilterOverrides }],
                    })

                    tile.filters_overrides = tileFilterOverrides
                    actions.refreshDashboardItem({ tile })
                    lemonToast.success('Tile filters saved')
                },
            })
        },
    })),

    subscriptions(() => ({
        dashboardMode: (dashboardMode, previousDashboardMode) => {
            if (previousDashboardMode !== DashboardMode.Edit && dashboardMode === DashboardMode.Edit) {
                clearDOMTextSelection()
                lemonToast.info('Now editing the dashboard – save to persist changes')
            }
        },
    })),

    actionToUrl(({ values }) => ({
        applyFilters: () => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = combineDashboardFilters(urlFilters, values.intermittentFilters)

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        setProperties: ({ properties }) => {
            if (!values.canAutoPreview) {
                return
            }

            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                properties,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        setDates: ({ date_from, date_to }) => {
            if (!values.canAutoPreview) {
                return
            }

            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                date_from,
                date_to,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        setBreakdownFilter: ({ breakdown_filter }) => {
            if (!values.canAutoPreview) {
                return
            }

            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                breakdown_filter,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLFilters(newUrlFilters) },
                currentLocation.hashParams,
            ]
        },
        overrideVariableValue: ({ variableId, value }) => {
            const { currentLocation } = router.values

            const currentVariable = values.variables.find((variable: Variable) => variable.id === variableId)

            if (!currentVariable) {
                return [currentLocation.pathname, currentLocation.searchParams, currentLocation.hashParams]
            }

            const urlVariables = parseURLVariables(currentLocation.searchParams)
            const newUrlVariables: Record<string, string> = {
                ...urlVariables,
                [currentVariable.code_name]: value,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLVariables(newUrlVariables) },
                currentLocation.hashParams,
            ]
        },
        resetUrlVariables: () => {
            const { currentLocation } = router.values
            const newSearchParams = { ...currentLocation.searchParams }
            delete newSearchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY]
            return [currentLocation.pathname, newSearchParams, currentLocation.hashParams]
        },
        resetUrlFilters: () => {
            const { currentLocation } = router.values
            const newSearchParams = { ...currentLocation.searchParams }
            delete newSearchParams[SEARCH_PARAM_FILTERS_KEY]
            return [currentLocation.pathname, newSearchParams, currentLocation.hashParams]
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

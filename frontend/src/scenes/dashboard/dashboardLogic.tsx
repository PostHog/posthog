import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors, sharedListeners } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api, { ApiMethodOptions, getJSONOrNull } from 'lib/api'
import { DataColorTheme } from 'lib/colors'
import { accessLevelSatisfied } from 'lib/components/AccessControlAction'
import { OrganizationMembershipLevel } from 'lib/constants'
import { Dayjs, dayjs, now } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { clearDOMTextSelection, getJSHeapMemory, shouldCancelQuery, toParams, uuid } from 'lib/utils'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import uniqBy from 'lodash.uniqby'
import { Layout, Layouts } from 'react-grid-layout'
import { calculateLayouts } from 'scenes/dashboard/tileLayouts'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { createMaxContextHelpers, MaxContextInput } from 'scenes/max/maxTypes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { variableDataLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableDataLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'
import { getQueryBasedDashboard } from '~/queries/nodes/InsightViz/utils'
import {
    BreakdownFilter,
    DashboardFilter,
    DataVisualizationNode,
    HogQLVariable,
    NodeKind,
    RefreshType,
} from '~/queries/schema/schema-general'
import {
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
import type { dashboardLogicType } from './dashboardLogicType'
import {
    AUTO_REFRESH_INITIAL_INTERVAL_SECONDS,
    BREAKPOINT_COLUMN_COUNTS,
    DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES,
    encodeURLVariables,
    getInsightWithRetry,
    IS_TEST_MODE,
    layoutsByTile,
    MAX_TILES_FOR_AUTOPREVIEW,
    parseURLVariables,
    QUERY_VARIABLES_KEY,
    runWithLimit,
} from './dashboardUtils'

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
        logic: [dashboardsModel, insightsModel, eventUsageLogic, variableDataLogic],
    })),

    props({} as DashboardLogicProps),

    key((props) => {
        if (typeof props.id !== 'number') {
            throw Error('Must init dashboardLogic with a numeric ID key')
        }
        return props.id
    }),

    actions(({ values }) => ({
        loadDashboard: (payload: {
            action:
                | 'initial_load'
                | 'initial_load_with_variables'
                | 'update'
                | 'refresh'
                | 'load_missing'
                | 'refresh_insights_on_filters_updated'
                | 'preview'
            manualDashboardRefresh?: boolean // whether the dashboard is being refreshed manually
        }) => payload,
        /** sets params from loadDashboard which can then be accessed in listeners (loadDashboardSuccess) */
        loadingDashboardItemsStarted: (action: string, manualDashboardRefresh: boolean) => ({
            action,
            manualDashboardRefresh,
        }),
        setInitialLoadResponseBytes: (responseBytes: number) => ({ responseBytes }),
        /** Called from insight tile, when a single insight is refreshed manually on the dashboard */
        triggerDashboardItemRefresh: (payload: { tile: DashboardTile<QueryBasedInsightModel> }) => payload,
        /** Triggered from dashboard refresh button, when user refreshes entire dashboard */
        triggerDashboardRefresh: true,
        /** helper used within this file to refresh provided tiles on the dashboard */
        updateDashboardItems: (payload: {
            tiles?: DashboardTile<QueryBasedInsightModel>[]
            action: string
            manualDashboardRefresh?: boolean
        }) => payload,

        triggerDashboardUpdate: (payload) => ({ payload }),
        /** The current state in which the dashboard is being viewed, see DashboardMode. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource | null) => ({ mode, source }),
        updateLayouts: (layouts: Layouts) => ({ layouts }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        updateTileColor: (tileId: number, color: string | null) => ({ tileId, color }),
        removeTile: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),

        resetInterval: true,
        setDates: (date_from: string | null, date_to: string | null) => ({
            date_from,
            date_to,
        }),
        setProperties: (properties: AnyPropertyFilter[] | null) => ({ properties }),
        setBreakdownFilter: (breakdown_filter: BreakdownFilter | null) => ({ breakdown_filter }),
        setBreakdownColorConfig: (config: BreakdownColorConfig) => ({ config }),
        setDataColorThemeId: (dataColorThemeId: number | null) => ({ dataColorThemeId }),
        setFiltersAndLayoutsAndVariables: (
            filters: DashboardFilter,
            variables: Record<string, HogQLVariable>,
            breakdownColors: BreakdownColorConfig[],
            dataColorThemeId: number | null
        ) => ({
            filters,
            variables,
            breakdownColors,
            dataColorThemeId,
        }),
        previewTemporaryFilters: true,
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

        abortQuery: (payload: { queryId: string; queryStartTime: number }) => payload,
        abortAnyRunningQuery: true,

        updateFiltersAndLayoutsAndVariables: true,
        overrideVariableValue: (variableId: string, value: any, isNull: boolean, reload?: boolean) => ({
            variableId,
            value,
            allVariables: values.variables,
            isNull,
            reload,
        }),
        setLoadLayoutFromServerOnPreview: (loadLayoutFromServerOnPreview: boolean) => ({
            loadLayoutFromServerOnPreview,
        }),

        resetVariables: () => ({ variables: values.insightVariables }),
        resetDashboardFilters: () => true,
        setAccessDeniedToDashboard: true,
        setURLVariables: (variables: Record<string, Partial<HogQLVariable>>) => ({ variables }),
        setInitialVariablesLoaded: (initialVariablesLoaded: boolean) => ({ initialVariablesLoaded }),
        updateDashboardLastRefresh: (lastDashboardRefresh: Dayjs) => ({ lastDashboardRefresh }),
    })),

    loaders(({ actions, props, values }) => ({
        dashboard: [
            null as DashboardType<QueryBasedInsightModel> | null,
            {
                /**
                 * TRICKY: Load dashboard only gets the dashboard meta + cached insights (as we pass `force_cache`)
                 * if manualDashboardRefresh is passed then in loadDashboardSuccess we trigger
                 * updateDashboardItems to refresh all insights with `force_blocking`
                 */
                loadDashboard: async ({ action, manualDashboardRefresh }, breakpoint) => {
                    actions.loadingDashboardItemsStarted(action, manualDashboardRefresh ?? false)
                    await breakpoint(200)

                    try {
                        const apiUrl = values.apiUrl(
                            'force_cache',
                            action === 'preview' ? values.temporaryFilters : undefined,
                            action === 'preview' ? values.temporaryVariables : undefined
                        )
                        const dashboardResponse: Response = await api.getResponse(apiUrl)
                        const dashboard: DashboardType<InsightModel> | null = await getJSONOrNull(dashboardResponse)

                        actions.setInitialLoadResponseBytes(getResponseBytes(dashboardResponse))

                        // don't update dashboard tile layouts if we're previewing
                        // we want to retain what the user has temporarily set
                        if (action === 'preview' && dashboard && !values.loadLayoutFromServerOnPreview) {
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
                        if (error.status === 403 && error.code === 'permission_denied') {
                            actions.setAccessDeniedToDashboard()
                        }
                        throw error
                    }
                },
                updateFiltersAndLayoutsAndVariables: async (_, breakpoint) => {
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
                                filters: values.filters,
                                variables: values.insightVariables,
                                breakdown_colors: values.temporaryBreakdownColors,
                                data_color_theme_id: values.dataColorThemeId,
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
                        delete newTile.id
                        if (newTile.text) {
                            newTile.text = { body: newTile.text.body } as TextModel
                        }

                        const dashboard: DashboardType<InsightModel> = await api.update(
                            `api/environments/${values.currentTeamId}/dashboards/${props.id}`,
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
        _dashboardLoading: [
            false,
            {
                loadDashboard: () => true,
                loadDashboardSuccess: () => false,
                loadDashboardFailure: () => false,
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
                previewTemporaryFilters: () => true,
            },
        ],
        cancellingPreview: [
            false,
            {
                // have to reload dashboard when when cancelling preview
                // and resetting filters
                resetDashboardFilters: () => true,
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
        temporaryVariables: [
            {} as Record<string, HogQLVariable>,
            {
                overrideVariableValue: (state, { variableId, value, allVariables, isNull }) => {
                    const foundExistingVar = allVariables.find((n) => n.id === variableId)
                    if (!foundExistingVar) {
                        return state
                    }

                    if (!value && !isNull) {
                        const newState = { ...state }
                        delete newState[variableId]
                        return newState
                    }

                    return {
                        ...state,
                        [variableId]: {
                            code_name: foundExistingVar.code_name,
                            variableId: foundExistingVar.id,
                            value,
                            isNull,
                        },
                    }
                },
                resetVariables: (_, { variables }) => ({ ...variables }),
                loadDashboardSuccess: (state, { dashboard, payload }) => {
                    return dashboard
                        ? {
                              ...state,
                              // don't update filters if we're previewing or initial load with variables
                              ...(payload?.action === 'preview' || payload?.action === 'initial_load_with_variables'
                                  ? {}
                                  : dashboard.variables ?? {}),
                          }
                        : state
                },
            },
        ],
        urlVariables: [
            {} as Record<string, Partial<HogQLVariable>>,
            {
                setURLVariables: (state, { variables }) => ({
                    ...state,
                    ...variables,
                }),
            },
        ],
        insightVariables: [
            {} as Record<string, HogQLVariable>,
            {
                setFiltersAndLayoutsAndVariables: (state, { variables }) => ({
                    ...state,
                    ...variables,
                }),
                loadDashboardSuccess: (state, { dashboard, payload }) =>
                    dashboard
                        ? {
                              ...state,
                              // don't update filters if we're previewing or initial load with variables
                              ...(payload?.action === 'preview' || payload?.action === 'initial_load_with_variables'
                                  ? {}
                                  : dashboard.variables ?? {}),
                          }
                        : state,
            },
        ],
        temporaryFilters: [
            {
                date_from: null,
                date_to: null,
                properties: null,
                breakdown_filter: null,
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
                setBreakdownFilter: (state, { breakdown_filter }) => ({
                    ...state,
                    breakdown_filter: breakdown_filter || null,
                }),
                loadDashboardSuccess: (state, { dashboard }) =>
                    dashboard
                        ? {
                              ...state,
                              date_from: dashboard?.filters.date_from || null,
                              date_to: dashboard?.filters.date_to || null,
                              properties: dashboard?.filters.properties || [],
                              breakdown_filter: dashboard?.filters.breakdown_filter || null,
                          }
                        : state,
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
        filters: [
            {
                date_from: null,
                date_to: null,
                properties: null,
                breakdown_filter: null,
            } as DashboardFilter,
            {
                setFiltersAndLayoutsAndVariables: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
                loadDashboardSuccess: (state, { dashboard, payload }) => {
                    const result = dashboard
                        ? {
                              ...state,
                              // don't update filters if we're previewing
                              ...(payload?.action === 'preview'
                                  ? {}
                                  : {
                                        date_from: dashboard?.filters.date_from || null,
                                        date_to: dashboard?.filters.date_to || null,
                                        properties: dashboard?.filters.properties || [],
                                        breakdown_filter: dashboard?.filters.breakdown_filter || null,
                                    }),
                          }
                        : state

                    return result
                },
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
        dashboardLoadData: [
            {
                action: '',
                manualDashboardRefresh: false,
                dashboardQueryId: '',
                startTime: 0,
                responseBytes: 0,
            } as {
                action: string
                manualDashboardRefresh: boolean
                dashboardQueryId: string
                startTime: number
                responseBytes: number
            },
            {
                loadingDashboardItemsStarted: (_, { action, manualDashboardRefresh }) => ({
                    action,
                    manualDashboardRefresh,
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
                setRefreshError: (state, { shortId }) => ({
                    ...state,
                    [shortId]: { error: true, timer: state[shortId]?.timer || null },
                }),
                updateDashboardItems: () => ({}),
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
        initialVariablesLoaded: [
            false,
            {
                setInitialVariablesLoaded: (_, { initialVariablesLoaded }) => initialVariablesLoaded,
            },
        ],

        lastDashboardRefresh: [
            null as Dayjs | null,
            {
                loadDashboardSuccess: (_, { dashboard }) => {
                    return dashboard?.last_refresh ? dayjs(dashboard.last_refresh) : null
                },
                updateDashboardLastRefresh: (_, { lastDashboardRefresh }) => lastDashboardRefresh,
            },
        ],
    })),
    selectors(() => ({
        canAutoPreview: [
            (s) => [s.dashboard],
            (dashboard) => (dashboard?.tiles.length || 0) < MAX_TILES_FOR_AUTOPREVIEW,
        ],
        filtersUpdated: [
            (s) => [s.temporaryFilters, s.dashboard],
            (temporaryFilters, dashboard) => {
                // both aren't falsy && both aren't equal
                const isDateFromUpdated =
                    !(!temporaryFilters.date_from && !dashboard?.filters.date_from) &&
                    temporaryFilters.date_from !== dashboard?.filters.date_from

                const isDateToUpdated =
                    !(!temporaryFilters.date_to && !dashboard?.filters.date_to) &&
                    temporaryFilters.date_to !== dashboard?.filters.date_to

                const isPropertiesUpdated =
                    JSON.stringify(temporaryFilters.properties ?? []) !==
                    JSON.stringify(dashboard?.filters.properties ?? [])

                const isBreakdownUpdated =
                    !(!temporaryFilters.breakdown_filter && !dashboard?.filters.breakdown_filter) &&
                    temporaryFilters.breakdown_filter !== dashboard?.filters.breakdown_filter

                return isDateFromUpdated || isDateToUpdated || isPropertiesUpdated || isBreakdownUpdated
            },
        ],
        dashboardVariables: [
            (s) => [s.dashboard, s.variables, s.temporaryVariables],
            (
                dashboard: DashboardType,
                allVariables: Variable[],
                temporaryVariables: Record<string, HogQLVariable>
            ): { variable: Variable; insights: string[] }[] => {
                const dataVizNodes = (dashboard?.tiles ?? [])
                    .map((n) => ({ query: n.insight?.query, title: n.insight?.name }))
                    .filter((n) => n.query?.kind === NodeKind.DataVisualizationNode)
                    .filter(
                        (n): n is { query: DataVisualizationNode; title: string } =>
                            Boolean(n.query) && Boolean(n.title)
                    )

                const hogQLVariables = dataVizNodes
                    .map((n) => n.query.source.variables)
                    .filter((n): n is Record<string, HogQLVariable> => Boolean(n))
                    .flatMap((n) => Object.values(n))

                const uniqueVars = uniqBy(hogQLVariables, (n) => n.variableId)
                return uniqueVars
                    .map((v) => {
                        const foundVar = allVariables.find((n) => n.id === v.variableId)

                        if (!foundVar) {
                            return null
                        }

                        const overridenValue = temporaryVariables[v.variableId]?.value
                        const overridenIsNull = temporaryVariables[v.variableId]?.isNull
                        // Overwrite the variable `value` from the insight
                        const resultVar: Variable = {
                            ...foundVar,
                            value: overridenValue,
                            isNull: overridenIsNull,
                        }

                        const insightsUsingVariable = dataVizNodes
                            .filter((n) => {
                                const vars = n.query.source.variables
                                if (!vars) {
                                    return false
                                }

                                return !!vars[v.variableId]
                            })
                            .map((n) => n.title)

                        return { variable: resultVar, insights: insightsUsingVariable }
                    })
                    .filter((n): n is { variable: Variable; insights: string[] } => Boolean(n?.variable))
            },
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
                return (
                    refresh?: RefreshType,
                    filtersOverride?: DashboardFilter,
                    variablesOverride?: Record<string, HogQLVariable>
                ) =>
                    `api/environments/${teamLogic.values.currentTeamId}/dashboards/${id}/?${toParams({
                        refresh,
                        filters_override: filtersOverride,
                        variables_override: variablesOverride,
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
            (s) => [s._dashboardLoading, s.refreshStatus, s.initialVariablesLoaded],
            (dashboardLoading, refreshStatus, initialVariablesLoaded) => {
                return (
                    dashboardLoading ||
                    Object.values(refreshStatus).some((s) => s.loading || s.queued) ||
                    (QUERY_VARIABLES_KEY in router.values.searchParams && !initialVariablesLoaded)
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
                    ? accessLevelSatisfied(AccessControlResourceType.Dashboard, dashboard.user_access_level, 'editor')
                    : true
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
            (s) => [s.dashboard, s._dashboardLoading, s.dashboardFailedToLoad, s.canEditDashboard],
            (dashboard, dashboardLoading, dashboardFailedToLoad, canEditDashboard): Breadcrumb[] => [
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
                    onRename: canEditDashboard
                        ? async (name) => {
                              if (dashboard) {
                                  await dashboardsModel.asyncActions.updateDashboard({
                                      id: dashboard.id,
                                      name,
                                      allowUndo: true,
                                  })
                              }
                          }
                        : undefined,
                },
            ],
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
                // Only render the new access control  on side panel if they are not using the old dashboard permissions (v1)
                return dashboard && dashboard.access_control_version === 'v2'
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
        // NOTE: noCache is used to prevent the dashboard from using cached results from previous loads when url variables override
        noCache: [(s) => [s.urlVariables], (urlVariables) => Object.keys(urlVariables).length > 0],
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
    events(({ actions, cache, props }) => ({
        afterMount: () => {
            // NOTE: initial dashboard load is done after variables are loaded in initialVariablesLoaded
            if (props.id) {
                if (props.dashboard) {
                    // If we already have dashboard data, use it. Should the data turn out to be stale,
                    // the loadDashboardSuccess listener will initiate a refresh
                    actions.loadDashboardSuccess(props.dashboard)
                } else {
                    if (!(QUERY_VARIABLES_KEY in router.values.searchParams)) {
                        actions.loadDashboard({
                            action: 'initial_load',
                        })
                    }
                }
            }
        },
        beforeUnmount: () => {
            actions.abortAnyRunningQuery()
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
        resetDashboardFilters: () => {
            actions.setDates(values.filters.date_from ?? null, values.filters.date_to ?? null)
            actions.setProperties(values.filters.properties ?? null)
            actions.setBreakdownFilter(values.filters.breakdown_filter ?? null)
        },
        updateFiltersAndLayoutsAndVariablesSuccess: () => {
            actions.loadDashboard({ action: 'update' })
        },
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
        /** Triggered from dashboard refresh button, when user refreshes entire dashboard */
        triggerDashboardRefresh: () => {
            // reset auto refresh interval
            actions.resetInterval()
            actions.loadDashboard({ action: 'refresh', manualDashboardRefresh: true })
        },
        /** Called when a single insight is refreshed manually on the dashboard */
        triggerDashboardItemRefresh: async ({ tile }, breakpoint) => {
            const dashboardId: number = props.id
            const insight = tile.insight

            if (!insight) {
                return
            }

            actions.setRefreshStatus(insight.short_id, true, true)

            try {
                breakpoint()

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
                    undefined,
                    values.temporaryVariables
                )

                if (refreshedInsight) {
                    dashboardsModel.actions.updateDashboardInsight(refreshedInsight)
                    actions.setRefreshStatus(insight.short_id)
                } else {
                    actions.setRefreshError(insight.short_id)
                }
            } catch {
                actions.setRefreshError(insight.short_id)
            }
        },
        updateDashboardItems: async ({ tiles, action, manualDashboardRefresh }, breakpoint) => {
            const dashboardId: number = props.id
            const sortedInsights = (tiles || values.insightTiles || [])
                // sort tiles so we poll them in the exact order they are computed on the backend
                .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
                .map((t) => t.insight)
                .filter((i): i is QueryBasedInsightModel => !!i)

            const insightsToRefresh = sortedInsights
            if (insightsToRefresh.length > 0) {
                // Set refresh status for all insights
                actions.setRefreshStatuses(
                    insightsToRefresh.map((item) => item.short_id),
                    false,
                    true
                )

                actions.abortAnyRunningQuery()
                cache.abortController = new AbortController()
                const methodOptions: ApiMethodOptions = { signal: cache.abortController.signal }

                const fetchSyncInsightFunctions = insightsToRefresh.map((insight) => async () => {
                    const queryId = uuid()
                    const queryStartTime = performance.now()
                    const dashboardId: number = props.id

                    // Set insight as refreshing
                    actions.setRefreshStatus(insight.short_id, true, true)

                    try {
                        const syncInsight = await getInsightWithRetry(
                            values.currentTeamId,
                            insight,
                            dashboardId,
                            queryId,
                            manualDashboardRefresh ? 'force_blocking' : 'blocking', // 'blocking' returns cached data if available, when manual refresh is triggered we want fresh results
                            methodOptions,
                            action === 'preview' ? values.temporaryFilters : undefined,
                            action === 'preview' ? values.temporaryVariables : undefined
                        )

                        if (syncInsight) {
                            if (action === 'preview' && syncInsight?.dashboard_tiles) {
                                syncInsight.dashboards = [dashboardId]
                            }
                            dashboardsModel.actions.updateDashboardInsight(syncInsight)
                            actions.setRefreshStatus(insight.short_id)
                        } else {
                            actions.setRefreshError(insight.short_id)
                        }
                    } catch (e: any) {
                        if (shouldCancelQuery(e)) {
                            console.warn(`Insight refresh cancelled for ${insight.short_id} due to abort signal:`, e)
                            actions.abortQuery({ queryId, queryStartTime })
                        } else {
                            actions.setRefreshError(insight.short_id)
                        }
                    }
                })

                // Execute the fetches with concurrency limit of 4
                await runWithLimit(fetchSyncInsightFunctions, 4)
                breakpoint()

                // REFRESH DONE: all insights have been refreshed

                // update last refresh time, only if we've forced a blocking refresh of the dashboard
                if (manualDashboardRefresh) {
                    actions.updateDashboardLastRefresh(dayjs())
                }

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
                    insights_fetched: insightsToRefresh.length,
                    insights_fetched_cached: values.dashboard?.tiles.reduce(
                        (acc, curr) => acc + (curr.is_cached ? 1 : 0),
                        0
                    ),
                    ...getJSHeapMemory(),
                })

                eventUsageLogic.actions.reportDashboardRefreshed(dashboardId, values.lastDashboardRefresh)
            }
        },
        setFiltersAndLayoutsAndVariables: ({ filters: { date_from, date_to } }) => {
            actions.updateFiltersAndLayoutsAndVariables()
            eventUsageLogic.actions.reportDashboardDateRangeChanged(date_from, date_to)
            eventUsageLogic.actions.reportDashboardPropertiesChanged()
        },
        setDashboardMode: async ({ mode, source }) => {
            if (mode === DashboardMode.Edit) {
                // Note: handled in subscriptions
            } else if (mode === null) {
                if (source === DashboardEventSource.DashboardHeaderDiscardChanges) {
                    // cancel edit mode changes

                    // reset filters to that before previewing
                    actions.resetDashboardFilters()
                    actions.resetVariables()

                    // reset tile data by relaoding dashboard
                    actions.loadDashboard({ action: 'preview' })

                    // also reset layout to that we stored in dashboardLayouts
                    // this is done in the reducer for dashboard
                } else if (source === DashboardEventSource.DashboardHeaderSaveDashboard) {
                    // save edit mode changes
                    actions.setFiltersAndLayoutsAndVariables(
                        values.temporaryFilters,
                        values.temporaryVariables,
                        values.temporaryBreakdownColors,
                        values.dataColorThemeId
                    )
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
                    values.lastDashboardRefresh &&
                    values.lastDashboardRefresh.isBefore(now().subtract(values.autoRefresh.interval, 'seconds'))
                ) {
                    actions.loadDashboard({ action: 'refresh' })
                }
                cache.autoRefreshInterval = window.setInterval(() => {
                    actions.loadDashboard({ action: 'refresh' })
                }, values.autoRefresh.interval * 1000)
            }
        },
        loadDashboardSuccess: (...args) => {
            void sharedListeners.reportLoadTiming(...args)

            if (!values.dashboard) {
                return // We hit a 404
            }

            // access stored values from dashboardLoadData
            // as we can't pass them down to this listener
            const { action, manualDashboardRefresh } = values.dashboardLoadData
            actions.updateDashboardItems({ action, manualDashboardRefresh })

            if (values.shouldReportOnAPILoad) {
                actions.setShouldReportOnAPILoad(false)
                actions.reportDashboardViewed()
            }
        },
        reportDashboardViewed: async (_, breakpoint) => {
            // Caching `dashboard`, as the dashboard might have unmounted after the breakpoint,
            // and "values.dashboard" will then fail
            const { dashboard, lastDashboardRefresh } = values
            if (dashboard) {
                eventUsageLogic.actions.reportDashboardViewed(dashboard, lastDashboardRefresh)
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
        previewTemporaryFilters: () => {
            actions.loadDashboard({ action: 'preview' })
        },
        setProperties: () => {
            if ((values.dashboard?.tiles.length || 0) < MAX_TILES_FOR_AUTOPREVIEW) {
                actions.loadDashboard({ action: 'preview' })
            }
        },
        setDates: () => {
            if ((values.dashboard?.tiles.length || 0) < MAX_TILES_FOR_AUTOPREVIEW) {
                actions.loadDashboard({ action: 'preview' })
            }
        },
        setBreakdownFilter: () => {
            if ((values.dashboard?.tiles.length || 0) < MAX_TILES_FOR_AUTOPREVIEW) {
                actions.loadDashboard({ action: 'preview' })
            }
        },
        overrideVariableValue: ({ reload, value, isNull }) => {
            if (reload) {
                actions.loadDashboard({ action: 'preview' })
                actions.setDashboardMode(DashboardMode.Edit, null)
            }

            if (!value && !isNull) {
                const hasOtherVariables = Object.values(values.temporaryVariables).some((v) => v.value || v.isNull)
                if (!hasOtherVariables) {
                    actions.resetVariables()
                }
            }
        },
        [variableDataLogic.actionTypes.getVariablesSuccess]: ({ variables }) => {
            // Only run this handler once on startup
            // This ensures variables are loaded before the dashboard is loaded and insights are refreshed
            if (values.initialVariablesLoaded) {
                return
            }

            // try to convert url variables to variables
            const urlVariables = values.urlVariables

            for (const [key, value] of Object.entries(urlVariables)) {
                const variable = variables.find((variable: Variable) => variable.code_name === key)
                if (variable) {
                    actions.overrideVariableValue(variable.id, value, variable.isNull || value === null)
                }
            }

            if (QUERY_VARIABLES_KEY in router.values.searchParams) {
                actions.loadDashboard({
                    action: 'initial_load_with_variables',
                })
            }

            actions.setInitialVariablesLoaded(true)
        },
        updateDashboardLastRefresh: ({ lastDashboardRefresh }) => {
            dashboardsModel.actions.updateDashboard({
                id: props.id,
                last_refresh: lastDashboardRefresh.toISOString(),
            })
        },
    })),

    subscriptions(({ values, actions }) => ({
        // This is used after initial variables are loaded in getVariableSuccess
        variables: (variables) => {
            if (!values.initialVariablesLoaded) {
                return
            }

            // try to convert url variables to variables
            const urlVariables = values.urlVariables

            for (const [key, value] of Object.entries(urlVariables)) {
                const variable = variables.find((variable: HogQLVariable) => variable.code_name === key)
                if (variable) {
                    actions.overrideVariableValue(variable.id, value, variable.isNull || value === null)
                }
            }
        },
        dashboardMode: (dashboardMode, previousDashboardMode) => {
            if (previousDashboardMode !== DashboardMode.Edit && dashboardMode === DashboardMode.Edit) {
                clearDOMTextSelection()
                lemonToast.info('Now editing the dashboard – save to persist changes')
            }
        },
    })),

    actionToUrl(({ values }) => ({
        overrideVariableValue: ({ variableId, value, isNull, allVariables }) => {
            const { currentLocation } = router.values

            const currentVariable = allVariables.find((variable: Variable) => variable.id === variableId)

            if (!currentVariable) {
                return [currentLocation.pathname, currentLocation.searchParams, currentLocation.hashParams]
            }

            const newUrlVariables: Record<string, string> = {
                ...values.urlVariables,
                [currentVariable.code_name]: value,
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }

            // If value is null and not explicitly set, remove it from the url variables
            if (!value && !isNull) {
                delete newUrlVariables[currentVariable.code_name]
                delete newSearchParams[QUERY_VARIABLES_KEY]
            }

            return [
                currentLocation.pathname,
                { ...newSearchParams, ...encodeURLVariables(newUrlVariables) },
                currentLocation.hashParams,
            ]
        },
        resetVariables: () => {
            const { currentLocation } = router.values
            const newSearchParams = {
                ...currentLocation.searchParams,
            }
            delete newSearchParams[QUERY_VARIABLES_KEY]
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

        '/dashboard/:id': (_, searchParams) => {
            const variables = parseURLVariables(searchParams)
            actions.setURLVariables(variables)
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

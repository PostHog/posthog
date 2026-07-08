import equal from 'fast-deep-equal'
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
import uniqBy from 'lodash.uniqby'
import { ResponsiveLayouts } from 'react-grid-layout'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'
import type { DashboardWidgetRunResultApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'
import { isWidgetConfigValidationError, updateDashboardWidgetTile } from '@posthog/products-dashboards/frontend/utils'
import {
    DASHBOARD_WIDGET_CATALOG,
    getDashboardWidgetCatalogEntry,
} from '@posthog/products-dashboards/frontend/widget_types/catalog'
import { DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE } from '@posthog/products-dashboards/frontend/widgets/constants'
import {
    applyIssueMetadataToWidgetListResult,
    type WidgetIssueMetadataContext,
    type WidgetIssueMetadataDelta,
} from '@posthog/products-dashboards/frontend/widgets/error_tracking/applyWidgetIssueMetadataChange'

import api, { ApiMethodOptions, getJSONOrNull } from 'lib/api'
import { ApiError } from 'lib/api-error'
import { DataColorTheme } from 'lib/colors'
import { quickFiltersSectionLogic } from 'lib/components/QuickFilters'
import { OrganizationMembershipLevel } from 'lib/constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs, now } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { clearDOMTextSelection, getJSHeapMemory, uuid } from 'lib/utils/dom'
import { DashboardEventSource, eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { objectsEqual } from 'lib/utils/objects'
import { shouldCancelQuery } from 'lib/utils/requests'
import { toParams } from 'lib/utils/url'
import { BREAKPOINTS, dashboardToSaveableTemplate, getDashboardTileDisplayName } from 'scenes/dashboard/dashboardUtils'
import {
    calculateDuplicateLayout,
    calculateInsertionLayout,
    calculateLayouts,
    DEFAULT_INSERTED_TILE_SIZE,
} from 'scenes/dashboard/tileLayouts'
import {
    chunkTileIds,
    fetchRunWidgets,
    findNewlyAddedWidgetTiles,
    WIDGET_CLIENT_TTL_MS,
} from 'scenes/dashboard/widgetFetchUtils'
import { createDashboardWidgetTileRefreshScheduler } from 'scenes/dashboard/widgetTileRefreshScheduler'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
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
    QuickFilterContext,
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
    DashboardTileBasicType,
    DashboardType,
    DashboardWidgetType,
    InsightColor,
    InsightModel,
    InsightShortId,
    ProjectTreeRef,
    QueryBasedInsightModel,
    TextModel,
    TileLayout,
} from '~/types'

import { getResponseBytes, sortDayJsDates } from '../insights/utils'
import { filterVariablesReferencedInQuery } from '../insights/utils/queryUtils'
import { teamLogic } from '../teamLogic'
import { AUTO_REFRESH_INITIAL_INTERVAL_SECONDS } from './dashboardConstants'
import { BreakdownColorConfig } from './DashboardInsightColorsModal'
import type { dashboardLogicType } from './dashboardLogicType'
import { dashboardQuickFiltersLogic } from './dashboardQuickFiltersLogic'
import {
    BREAKPOINT_COLUMN_COUNTS,
    DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES,
    IS_TEST_MODE,
    DEFAULT_AUTO_PREVIEW_TILE_LIMIT,
    QUICK_FILTER_DEBOUNCE_MS,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    combineDashboardFilters,
    encodeURLFilters,
    encodeURLVariables,
    getDashboardWidgetType,
    getInsightWithRetry,
    isLayoutEditEventSource,
    layoutsByTile,
    parseURLFilters,
    parseURLVariables,
    runWithLimit,
    shouldSharedDashboardAutoForceForStaleTime,
    shouldSnapshotUrlAtEditModeEntry,
} from './dashboardUtils'
import { TileFiltersOverride } from './TileFiltersOverride'
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

export interface PendingInsertion {
    x: number
    y: number
    // Width override for the full-width fallback when the hovered column can't anchor the tile; else null.
    w: number | null
}

const tileLayoutsFromDashboard = (
    dashboard: DashboardType<QueryBasedInsightModel> | null | undefined
): Record<number, DashboardTile['layouts']> => {
    const tileIdToLayouts: Record<number, DashboardTile['layouts']> = {}
    dashboard?.tiles.forEach((tile: DashboardTile<QueryBasedInsightModel>) => {
        tileIdToLayouts[tile.id] = tile.layouts
    })
    return tileIdToLayouts
}

function mergeUpdatedWidgetTileIntoDashboard(
    dashboard: DashboardType<QueryBasedInsightModel>,
    updatedTile: DashboardTile<QueryBasedInsightModel>
): DashboardType<QueryBasedInsightModel> | null {
    return getQueryBasedDashboard({
        ...dashboard,
        tiles: dashboard.tiles.map((existingTile) => {
            if (existingTile.id !== updatedTile.id) {
                return existingTile
            }

            return {
                ...existingTile,
                ...updatedTile,
                widget:
                    existingTile.widget && updatedTile.widget
                        ? { ...existingTile.widget, ...updatedTile.widget }
                        : (updatedTile.widget ?? existingTile.widget),
            }
        }),
    } as DashboardType<InsightModel>)
}

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
            dashboardQuickFiltersLogic,
            ['quickFilterPropertyFiltersById'],
        ],
        logic: [dashboardsModel, insightsModel, eventUsageLogic],
    })),

    props({} as DashboardLogicProps),

    key((props) => {
        // `typeof NaN === 'number'` — check finiteness explicitly so a NaN id surfaces loudly
        // instead of mounting a stuck-NotFound logic instance.
        if (typeof props.id !== 'number' || !Number.isFinite(props.id)) {
            throw Error(`dashboardLogic key() received non-finite id: ${String(props.id)}`)
        }
        return props.id
    }),

    connect(() => ({
        actions: [
            quickFiltersSectionLogic({ context: QuickFilterContext.Dashboards }),
            ['quickFiltersCommitted', 'quickFiltersUrlRestoreComplete'],
        ],
    })),

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
        /**
         * If the latest tile data is older than SHARED_DASHBOARD_AUTO_FORCE_IF_STALE_MINUTES,
         * queue a single force-blocking refresh on the next microtask. Reads
         * `effectiveLastRefresh` from values, so always sees the live age — no closure.
         */
        forceRefreshIfStale: true,
        /** Manually refresh a single insight from the insight card on the dashboard. */
        refreshDashboardItem: (payload: { tile: DashboardTile<QueryBasedInsightModel> }) => payload,
        /** Refresh tiles of a loaded dashboard e.g. stale tiles after initial load, previewed tiles after applying filters, etc. */
        refreshDashboardItems: (payload: {
            action: RefreshDashboardItemsAction | DashboardLoadAction
            forceRefresh?: boolean
        }) => payload,
        refreshDashboardWidgets: (payload: { tileIds: number[]; forceRefresh?: boolean }) => payload,
        /** Debounced run_widgets refresh for a single tile (tile filters). */
        scheduleRefreshDashboardWidgets: (tileId: number) => ({ tileId }),
        applyWidgetIssueMetadataChange: (payload: {
            tileId: number
            issueId: string
            delta: WidgetIssueMetadataDelta
            context: WidgetIssueMetadataContext
        }) => payload,
        setWidgetRunResults: (results: Record<number, DashboardWidgetRunResultApi>) => ({ results }),
        setWidgetRefreshStatuses: (tileIds: number[], loading: boolean, error?: string | null) => ({
            tileIds,
            loading,
            error,
        }),
        addWidgetTiles: (payload: {
            dashboardId: number
            widgets: { widgetType: string; config: Record<string, unknown> }[]
        }) => payload,
        setAddWidgetModalOpen: (open: boolean) => ({ open }),
        toggleAddWidgetSelectedType: (widgetType: string) => ({ widgetType }),
        clearAddWidgetSelectedTypes: true,
        toggleAddWidgetCollapsedGroup: (groupId: string) => ({ groupId }),
        addWidgetTileFinished: true,
        /** One-shot signal asking the view to scroll the dashboard to the bottom (e.g. after adding tiles). */
        requestScrollToBottom: true,
        /** Update a single refresh status. */
        setRefreshStatus: (shortId: InsightShortId, loading = false, queued = false) => ({ shortId, loading, queued }),
        /** Update multiple refresh statuses. */
        setRefreshStatuses: (shortIds: InsightShortId[], loading = false, queued = false) => ({
            shortIds,
            loading,
            queued,
        }),
        setRefreshError: (shortId: InsightShortId, error?: Error) => ({ shortId, error }),
        /** Number of insights enrolled in the current refresh cycle, captured up front. */
        setRefreshTilesTotal: (total: number) => ({ total }),
        abortQuery: (payload: { queryId: string; queryStartTime: number; shortId: InsightShortId }) => payload,
        abortAnyRunningQuery: true,
        cancelDashboardRefresh: true,

        /**
         * Auto-refresh while on page.
         **/
        setAutoRefresh: (enabled: boolean, interval: number) => ({ enabled, interval }),
        resetInterval: true,

        /*
         * Dashboard filters & variables.
         */
        setDates: (date_from: string | null, date_to: string | null | undefined, explicitDate?: boolean) => ({
            date_from,
            date_to,
            explicitDate,
        }),
        setProperties: (properties: AnyPropertyFilter[] | null) => ({ properties }),
        setBreakdownFilter: (breakdown_filter: BreakdownFilter | null) => ({ breakdown_filter }),
        setExternalFilters: (filters: DashboardFilter) => ({ filters }),
        saveEditModeChanges: () => true,
        resetUrlFilters: () => true,
        resetIntermittentFilters: () => true,
        restoreUrlStateAtEditModeEntry: (snapshot: { filters?: unknown; variables?: unknown } | null) => ({
            snapshot,
        }),
        setUrlSearchParamsAtEditModeEntry: (snapshot: { filters?: unknown; variables?: unknown }) => ({ snapshot }),
        applyFilters: true,
        resetUrlVariables: true,
        setInitialVariablesLoaded: (initialVariablesLoaded: boolean) => ({ initialVariablesLoaded }),
        setInitialQuickFiltersLoaded: (initialQuickFiltersLoaded: boolean) => ({ initialQuickFiltersLoaded }),
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
        updateDashboardTags: (tags: string[]) => ({ tags }),
        /** Update page visibility for virtualized rendering. */
        setPageVisibility: (visible: boolean) => ({ visible }),
        setSubscriptionMode: (enabled: boolean, id?: number | 'new') => ({ enabled, id }),
        /** Set the dashboard mode, see DashboardMode for details. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource) => ({ mode, source }),
        /** Exit edit mode, prompting to confirm if there are unsaved changes. */
        cancelEditMode: true,
        /** Make it easier to handle organizing the layout when theres lots of tiles by zooming out */
        setLayoutZoom: (layoutZoom: number) => ({ layoutZoom }),
        /** Optimistic pin/unpin toggle. */
        togglePinned: true,
        /** Open/close the Terraform export modal. */
        setTerraformModalOpen: (open: boolean) => ({ open }),

        /**
         * Dashboard layout & tiles.
         */
        updateLayouts: (layouts: ResponsiveLayouts) => ({ layouts }),
        setPendingInsertion: (pendingInsertion: PendingInsertion | null) => ({ pendingInsertion }),
        applyPendingInsertion: true,
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        updateTileColor: (tileId: number, color: InsightColor | null) => ({ tileId, color }),
        toggleTileDescription: (tileId: number) => ({ tileId }),
        setTileProperty: (tileId: number, properties: Partial<Pick<DashboardTile, 'color' | 'show_description'>>) => ({
            tileId,
            properties,
        }),
        duplicateTile: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),
        removeTile: (tile: DashboardTile<QueryBasedInsightModel>) => ({ tile }),
        addOptimisticTiles: (tiles: DashboardTile<QueryBasedInsightModel>[]) => ({ tiles }),
        removeOptimisticTiles: true,
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
        copyToDashboard: (
            tile: DashboardTile<QueryBasedInsightModel>,
            fromDashboard: number,
            toDashboard: number,
            toDashboardName: string
        ) => ({
            tile,
            fromDashboard,
            toDashboard,
            toDashboardName,
        }),
        setTextTileId: (textTileId: number | 'new' | null) => ({ textTileId }),
        setButtonTileId: (buttonTileId: number | 'new' | null) => ({ buttonTileId }),
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

    loaders(({ actions, props, values, cache }) => ({
        dashboard: [
            null as DashboardType<QueryBasedInsightModel> | null,
            {
                loadDashboard: async ({ action }, breakpoint) => {
                    actions.loadingDashboardItemsStarted(action)

                    await breakpoint(200)

                    try {
                        const apiUrl = values.apiUrl('force_cache', values.filtersOverrideForLoad, values.urlVariables)
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
                            filtersOverride: values.filtersOverrideForLoad,
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
                    cache.dashboardChangesPersisted = false
                    try {
                        // Only persist sm layouts; xs layouts are derived on the fly
                        const layoutsToUpdate = (values.dashboard?.tiles || []).map((tile) => ({
                            id: tile.id,
                            layouts: tile.layouts?.sm ? { sm: tile.layouts.sm } : {},
                        }))

                        const currentDashboard = values.dashboard
                        if (!currentDashboard) {
                            return null
                        }

                        const persistedFilters = currentDashboard.persisted_filters || {}
                        const persistedVariables = currentDashboard.persisted_variables || {}
                        const persistedBreakdownColors = currentDashboard.breakdown_colors || []
                        const persistedThemeId = currentDashboard.data_color_theme_id ?? null

                        const filtersChanged = !equal(persistedFilters, values.effectiveEditBarFilters || {})
                        const variablesChanged = !equal(
                            persistedVariables,
                            values.effectiveDashboardVariableOverrides || {}
                        )
                        const breakdownColorsChanged = !equal(
                            persistedBreakdownColors,
                            values.temporaryBreakdownColors || []
                        )
                        const themeChanged = (values.dataColorThemeId ?? null) !== persistedThemeId

                        const layoutsChanged = (currentDashboard.tiles || []).some((tile) => {
                            const originalLayouts = values.dashboardLayouts?.[tile.id]?.sm
                            const updatedLayouts = layoutsToUpdate.find((t) => t.id === tile.id)?.layouts?.sm
                            return !equal(originalLayouts || {}, updatedLayouts || {})
                        })

                        if (
                            !filtersChanged &&
                            !variablesChanged &&
                            !breakdownColorsChanged &&
                            !themeChanged &&
                            !layoutsChanged
                        ) {
                            actions.resetUrlFilters()
                            actions.resetUrlVariables()
                            return currentDashboard
                        }

                        breakpoint()

                        // Dashboard filters or variables changed—each tile must reload so charts match the
                        // settings you just saved (same flow as Apply filters).
                        const shouldRefreshTilesAfterSave = filtersChanged || variablesChanged

                        const updatedDashboard: DashboardType<InsightModel> = await api.update(
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
                        if (shouldRefreshTilesAfterSave) {
                            cache.shouldRefreshTilesAfterSave = true
                        }
                        cache.dashboardChangesPersisted = true
                        return getQueryBasedDashboard(updatedDashboard)
                    } catch (e) {
                        lemonToast.error('Could not update dashboard: ' + String(e))
                        return values.dashboard
                    }
                },
                removeTile: async ({ tile }) => {
                    // The reducer drops the tile optimistically; here we only persist and roll back on failure.
                    try {
                        await api.update(`api/environments/${values.currentTeamId}/dashboards/${props.id}`, {
                            tiles: [{ id: tile.id, deleted: true }],
                        })
                        dashboardsModel.actions.tileRemovedFromDashboard({
                            tile: tile,
                            dashboardId: props.id,
                        })

                        return values.dashboard
                    } catch (e) {
                        lemonToast.error('Could not remove tile from dashboard: ' + String(e))
                        // Re-insert the tile (its layout puts it back in place) and suppress the undo toast.
                        cache.removedTileForUndo = undefined
                        return {
                            ...values.dashboard,
                            tiles: [...(values.tiles || []), tile],
                        } as DashboardType<QueryBasedInsightModel>
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

                        const { duplicateLayouts, tilesToUpdate } = calculateDuplicateLayout(values.layouts, tile.id)

                        const dashboard: DashboardType<InsightModel> = await api.update(
                            `api/environments/${values.currentTeamId}/dashboards/${props.id}`,
                            {
                                duplicate_tiles: [{ ...newTile, layouts: duplicateLayouts }],
                                tiles: tilesToUpdate.length > 0 ? tilesToUpdate : undefined,
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
                            to_dashboard: toDashboard,
                        }
                    )
                    return getQueryBasedDashboard(dashboard)
                },
                copyToDashboard: async ({ tile, fromDashboard, toDashboard, toDashboardName }) => {
                    if (!tile?.insight && !tile?.text && !tile?.button_tile && !tile?.widget) {
                        return values.dashboard
                    }
                    if (tile.button_tile && !tile.insight && !tile.text && !tile.widget) {
                        lemonToast.error('Copying button tiles to another dashboard is not supported')
                        return values.dashboard
                    }
                    if (fromDashboard === toDashboard) {
                        return values.dashboard
                    }

                    if (fromDashboard !== props.id) {
                        return values.dashboard
                    }

                    const widgetType = getDashboardWidgetType(tile)

                    const copyToastLabel: Record<DashboardWidgetType, string> = {
                        insight: 'Insight',
                        text: 'Text card',
                        button_tile: 'Button',
                        widget: 'Widget',
                    }
                    const copyErrorPrefix: Record<DashboardWidgetType, string> = {
                        insight: 'Could not copy insight',
                        text: 'Could not copy text card',
                        button_tile: 'Could not copy button tile',
                        widget: 'Could not copy widget',
                    }

                    try {
                        await api.create(
                            `api/environments/${teamLogic.values.currentTeamId}/dashboards/${toDashboard}/copy_tile`,
                            { fromDashboardId: fromDashboard, tileId: tile.id }
                        )

                        if (tile.insight) {
                            const insight = tile.insight
                            const nextDashboards = insight.dashboards?.includes(toDashboard)
                                ? insight.dashboards
                                : [...(insight.dashboards || []), toDashboard]
                            dashboardsModel.actions.updateDashboardInsight({ ...insight, dashboards: nextDashboards }, [
                                toDashboard,
                            ])
                        }

                        eventUsageLogic.actions.reportCopiedDashboardTileToDashboard(
                            fromDashboard,
                            toDashboard,
                            widgetType
                        )

                        lemonToast.success(
                            <>
                                {copyToastLabel[widgetType]} copied to{' '}
                                <b>
                                    <Link to={urls.dashboard(toDashboard)}>{toDashboardName}</Link>
                                </b>
                            </>
                        )
                    } catch (e) {
                        lemonToast.error(`${copyErrorPrefix[widgetType]} to dashboard: ${String(e)}`)
                    }

                    return values.dashboard
                },
            },
        ],
        widgetTileUpdate: [
            null,
            {
                updateWidgetTile: async ({
                    tile,
                    config,
                    name,
                    description,
                }: {
                    tile: DashboardTile<QueryBasedInsightModel>
                    config?: Record<string, unknown>
                    name?: string | null
                    description?: string
                }) => {
                    if (!values.dashboard?.id || !tile.widget) {
                        return null
                    }
                    if (config === undefined && name === undefined && description === undefined) {
                        return null
                    }

                    try {
                        const shouldShowDescription =
                            description !== undefined &&
                            description.trim().length > 0 &&
                            tile.show_description === false

                        const updatedTile = await updateDashboardWidgetTile({
                            teamId: teamLogic.values.currentTeamId!,
                            dashboardId: values.dashboard.id,
                            tile,
                            config,
                            name,
                            description,
                            showDescription: shouldShowDescription ? true : undefined,
                        })
                        const dashboard = mergeUpdatedWidgetTileIntoDashboard(values.dashboard, updatedTile)
                        if (dashboard) {
                            dashboardsModel.actions.updateDashboardSuccess(dashboard)
                        }
                        if (config !== undefined) {
                            actions.scheduleRefreshDashboardWidgets(tile.id)
                        }
                        return null
                    } catch (e) {
                        if (config !== undefined && isWidgetConfigValidationError(e)) {
                            throw e
                        }
                        lemonToast.error(e instanceof ApiError ? (e.detail ?? e.message) : 'Could not update widget')
                        throw e
                    }
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
                loadDashboardSuccess: (_, { dashboard }) => tileLayoutsFromDashboard(dashboard),
                loadDashboardMetadataSuccess: (_, { dashboard }) => tileLayoutsFromDashboard(dashboard),
                saveEditModeChangesSuccess: (_, { dashboard }) => tileLayoutsFromDashboard(dashboard),
                receiveTileFromStream: (state, { tile }) => ({
                    ...state,
                    [tile.id]: tile.layouts,
                }),
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
        layoutZoom: [
            1,
            {
                setLayoutZoom: (_state: number, { layoutZoom }: { layoutZoom: number }) =>
                    Math.min(1, Math.max(0.25, layoutZoom)),
                updateContainerWidth: (state: number, { columns }: { columns: number }) => (columns === 1 ? 1 : state),
            },
        ],
        dashboard: [
            null as DashboardType<QueryBasedInsightModel> | null,
            {
                updateLayouts: (state, { layouts }) => {
                    const itemLayouts = layoutsByTile(layouts)

                    // Only persist sm layouts; xs layouts are derived on the fly
                    return {
                        ...state,
                        tiles: state?.tiles?.map((tile) => ({
                            ...tile,
                            layouts: itemLayouts[tile.id]?.sm ? { sm: itemLayouts[tile.id].sm } : {},
                        })),
                    } as DashboardType<QueryBasedInsightModel>
                },
                setTileProperty: (state, { tileId, properties }) => {
                    return {
                        ...state,
                        tiles: state?.tiles?.map((tile) => (tile.id === tileId ? { ...tile, ...properties } : tile)),
                    } as DashboardType<QueryBasedInsightModel>
                },
                removeTile: (state, { tile }) => {
                    // Optimistically drop the tile so the grid reflows immediately; the loader rolls back on failure.
                    return {
                        ...state,
                        tiles: state?.tiles?.filter((t) => t.id !== tile.id),
                    } as DashboardType<QueryBasedInsightModel>
                },
                addOptimisticTiles: (state, { tiles }) => {
                    // Show freshly-added tiles before the save round-trips; the server response replaces them.
                    // Optimistic tiles carry a negative id (see the updateDashboard listener) until then.
                    return state
                        ? ({
                              ...state,
                              tiles: [...(state.tiles || []), ...tiles],
                          } as DashboardType<QueryBasedInsightModel>)
                        : state
                },
                removeOptimisticTiles: (state) => {
                    // Roll back every not-yet-persisted tile (negative id) when a save fails.
                    return state
                        ? ({
                              ...state,
                              tiles: (state.tiles || []).filter((t) => t.id >= 0),
                          } as DashboardType<QueryBasedInsightModel>)
                        : state
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
                    { insight, extraDashboardIds, sourceDashboardId }
                ) => {
                    if (sourceDashboardId != null && sourceDashboardId !== props.id) {
                        // Insight payload is from another dashboard's refresh; merged query/date range must not leak here.
                        return state
                    }
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

                    // A bare PATCH (rename, display-option persist) doesn't recompute the insight, so
                    // its response carries `result: null` and stale-but-empty cache metadata. Keep the
                    // tile's already-computed chart data instead of blanking it into "Chart data didn't load".
                    const existing = tiles[tileIndex].insight as QueryBasedInsightModel
                    tiles[tileIndex] = {
                        ...tiles[tileIndex],
                        insight: {
                            ...existing,
                            ...item,
                            result: item.result ?? existing.result,
                            last_refresh: item.last_refresh ?? existing.last_refresh,
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
                // Drop only the aborted tile so sibling tiles still in flight stay tracked; wiping the
                // whole map here would make them count as completed and overstate "X out of Y".
                abortQuery: (state, { shortId }) => {
                    const { [shortId]: _aborted, ...rest } = state
                    return rest
                },
                cancelDashboardRefresh: () => ({}),
            },
        ],
        // Denominator for "X out of Y", pinned up front so Y stays fixed while tiles enroll one by one.
        // null = no batch pinned → selector falls back to the live map size (single-insight refreshes).
        // Reset on cycle boundaries only, never on the per-tile abortQuery, so an aborted tile can't shrink Y.
        refreshTilesTotal: [
            null as number | null,
            {
                setRefreshTilesTotal: (_, { total }) => total,
                refreshDashboardItems: () => null,
                cancelDashboardRefresh: () => null,
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
        layoutEditMode: [
            false,
            {
                setDashboardMode: (_, { mode, source }) => {
                    if (mode !== DashboardMode.Edit) {
                        return false
                    }
                    if (isLayoutEditEventSource(source)) {
                        return true
                    }
                    return false
                },
            },
        ],
        pendingInsertion: [
            null as PendingInsertion | null,
            {
                setPendingInsertion: (_, { pendingInsertion }) => pendingInsertion,
                // Clear on a real mode switch, but not on mode === null — the text/button add flow routes through it.
                setDashboardMode: (state, { mode }) => (mode != null ? null : state),
                // No hideAddInsightToDashboardModal handler on purpose: it fires as the insight is added, so
                // clearing there would drop the target before the tile lands.
            },
        ],
        urlSearchParamsAtEditModeEntry: [
            null as { filters?: unknown; variables?: unknown } | null,
            {
                setUrlSearchParamsAtEditModeEntry: (_, { snapshot }) => snapshot,
                setDashboardMode: (snapshot, { mode, source }) => {
                    if (mode === null && source !== DashboardEventSource.DashboardHeaderDiscardChanges) {
                        return null
                    }
                    return snapshot
                },
                restoreUrlStateAtEditModeEntry: () => null,
                saveEditModeChangesSuccess: () => null,
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

        showButtonTileModal: [
            false,
            {
                setButtonTileId: (_, { buttonTileId }) => !!buttonTileId,
            },
        ],
        buttonTileId: [
            null as number | 'new' | null,
            {
                setButtonTileId: (_, { buttonTileId }) => buttonTileId,
            },
        ],

        isPinned: [
            false,
            {
                loadDashboardSuccess: (_, { dashboard }) => !!dashboard?.pinned,
                togglePinned: (state) => !state,
            },
        ],

        terraformModalOpen: [
            false,
            {
                setTerraformModalOpen: (_, { open }) => open,
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
        /** Quick filter URL restoration */
        initialQuickFiltersLoaded: [
            false,
            {
                setInitialQuickFiltersLoaded: (_, { initialQuickFiltersLoaded }) => initialQuickFiltersLoaded,
            },
        ],
        externalFilters: [
            {} as DashboardFilter,
            {
                setExternalFilters: (_: DashboardFilter, { filters }: { filters: DashboardFilter }) => filters,
            },
        ],

        intermittentFilters: [
            {
                date_from: undefined,
                date_to: undefined,
                properties: undefined,
                breakdown_filter: undefined,
                explicitDate: undefined,
            } as DashboardFilter,
            {
                setDates: (state, { date_from, date_to, explicitDate }) => ({
                    ...state,
                    date_from,
                    date_to,
                    explicitDate,
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
                    explicitDate: undefined,
                }),
            },
        ],
        isSavingTags: [
            false,
            {
                updateDashboardTags: () => true,
                [dashboardsModel.actionTypes.updateDashboardSuccess]: (state, { dashboard }) => {
                    return dashboard && dashboard.id === props.id ? false : state
                },
                [dashboardsModel.actionTypes.updateDashboardFailure]: () => false,
            },
        ],
        widgetResultsByTileId: [
            {} as Record<number, DashboardWidgetRunResultApi>,
            {
                setWidgetRunResults: (state, { results }) => ({ ...state, ...results }),
                applyWidgetIssueMetadataChange: (state, { tileId, issueId, delta, context }) => {
                    const run = state[tileId]
                    if (!run?.result || typeof run.result !== 'object') {
                        return state
                    }
                    const nextResult = applyIssueMetadataToWidgetListResult(
                        run.result as Parameters<typeof applyIssueMetadataToWidgetListResult>[0],
                        issueId,
                        delta,
                        context
                    )
                    return {
                        ...state,
                        [tileId]: {
                            ...run,
                            result: nextResult,
                        },
                    }
                },
            },
        ],
        widgetRefreshStatus: [
            {} as Record<number, { loading?: boolean; error?: string | null; fetchedAt?: number }>,
            {
                setWidgetRefreshStatuses: (state, { tileIds, loading, error }) => ({
                    ...state,
                    ...Object.fromEntries(
                        tileIds.map((tileId) => [
                            tileId,
                            loading
                                ? { loading: true, error: null }
                                : { loading: false, error: error ?? null, fetchedAt: Date.now() },
                        ])
                    ),
                }),
                setWidgetRunResults: (state, { results }) => {
                    const next = { ...state }
                    for (const tileId of Object.keys(results).map(Number)) {
                        next[tileId] = { ...next[tileId], loading: false, fetchedAt: Date.now() }
                    }
                    return next
                },
            },
        ],
        addWidgetTileLoading: [
            false,
            {
                addWidgetTiles: () => true,
                addWidgetTileFinished: () => false,
            },
        ],
        // Incremented on each scroll-to-bottom request; the view effects on the change.
        scrollToBottomSignal: [
            0,
            {
                requestScrollToBottom: (state) => state + 1,
            },
        ],
        addWidgetModalOpen: [
            false,
            {
                setAddWidgetModalOpen: (_, { open }) => open,
            },
        ],
        addWidgetSelectedTypes: [
            [] as string[],
            {
                toggleAddWidgetSelectedType: (state, { widgetType }) => {
                    const selected = new Set(state)
                    if (selected.has(widgetType)) {
                        selected.delete(widgetType)
                    } else {
                        selected.add(widgetType)
                    }
                    return Array.from(selected)
                },
                clearAddWidgetSelectedTypes: () => [],
            },
        ],
        addWidgetCollapsedGroups: [
            [] as string[],
            {
                setAddWidgetModalOpen: (state, { open }) => (open ? [] : state),
                toggleAddWidgetCollapsedGroup: (state, { groupId }) => {
                    const collapsed = new Set(state)
                    if (collapsed.has(groupId)) {
                        collapsed.delete(groupId)
                    } else {
                        collapsed.add(groupId)
                    }
                    return Array.from(collapsed)
                },
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
            (s) => [s.insightTiles],
            (insightTiles) => {
                const payload = getFeatureFlagPayload(FEATURE_FLAGS.DASHBOARD_AUTO_PREVIEW_LIMIT)
                const limit = typeof payload === 'number' ? payload : DEFAULT_AUTO_PREVIEW_TILE_LIMIT
                // The limit is about the number of insights on a dashboard (per the flag's intent),
                // so count insight tiles only — not text, button, or widget tiles.
                return insightTiles.length < limit
            },
        ],
        hasIntermittentFilters: [
            (s) => [s.intermittentFilters],
            (intermittentFilters) => Object.values(intermittentFilters).some((filter) => filter !== undefined),
        ],
        hasUrlFilters: [
            (s) => [s.urlFilters],
            (urlFilters) => Object.values(urlFilters).some((filter) => filter !== undefined),
        ],
        showApplyFiltersBanner: [
            (s) => [s.canAutoPreview, s.hasIntermittentFilters],
            (canAutoPreview, hasIntermittentFilters) => !canAutoPreview && hasIntermittentFilters,
        ],
        urlFilters: [() => [router.selectors.searchParams], (searchParams) => parseURLFilters(searchParams)],
        scopedQuickFiltersAsPropertyFilters: [
            (s) => [s.dashboard, s.quickFilterPropertyFiltersById],
            (
                dashboard: DashboardType<QueryBasedInsightModel> | null,
                quickFilterPropertyFiltersById: Record<string, AnyPropertyFilter>
            ): AnyPropertyFilter[] => {
                const allowedIds = dashboard?.quick_filter_ids
                if (!allowedIds || allowedIds.length === 0) {
                    return []
                }
                return allowedIds
                    .filter((id) => id in quickFilterPropertyFiltersById)
                    .map((id) => quickFilterPropertyFiltersById[id])
            },
        ],
        filtersOverrideForLoad: [
            (s) => [
                s.externalFilters,
                s.urlFilters,
                s.scopedQuickFiltersAsPropertyFilters,
                s.dashboard,
                s.quickFilterPropertyFiltersById,
            ],
            (externalFilters, urlFilters, scopedQuickFilters, dashboard, quickFilterPropertyFiltersById) => {
                const combined = combineDashboardFilters(externalFilters, urlFilters)
                // Before the dashboard loads, scopedQuickFiltersAsPropertyFilters is
                // empty because scoping needs dashboard.quick_filter_ids. Fall back to
                // all URL-restored quick filter properties — the URL only contains
                // filters set on this dashboard, so unscoped is safe for initial load.
                const quickFilters =
                    scopedQuickFilters.length > 0
                        ? scopedQuickFilters
                        : !dashboard
                          ? Object.values(quickFilterPropertyFiltersById)
                          : []
                if (quickFilters.length > 0) {
                    return { ...combined, properties: [...(combined.properties || []), ...quickFilters] }
                }
                return combined
            },
        ],
        effectiveEditBarFilters: [
            (s) => [s.dashboard, s.externalFilters, s.urlFilters, s.intermittentFilters],
            (dashboard, externalFilters, urlFilters, intermittentFilters) => {
                const effectiveEditBarFilters = combineDashboardFilters(
                    dashboard?.persisted_filters || {},
                    externalFilters,
                    urlFilters,
                    intermittentFilters
                )
                return effectiveEditBarFilters
            },
        ],
        effectiveRefreshFilters: [
            (s) => [s.dashboard, s.externalFilters, s.urlFilters, s.scopedQuickFiltersAsPropertyFilters],
            (
                dashboard: DashboardType<QueryBasedInsightModel> | null,
                externalFilters: DashboardFilter,
                urlFilters: DashboardFilter,
                scopedQuickFilters: AnyPropertyFilter[]
            ): DashboardFilter => {
                const combined = combineDashboardFilters(
                    dashboard?.persisted_filters || {},
                    externalFilters,
                    urlFilters
                )
                if (scopedQuickFilters.length > 0) {
                    return { ...combined, properties: [...(combined.properties || []), ...scopedQuickFilters] }
                }
                return combined
            },
        ],
        effectiveDashboardVariableOverrides: [
            (s) => [s.dashboard, s.urlVariables],
            (dashboard, urlVariables) => ({ ...dashboard?.persisted_variables, ...urlVariables }),
        ],
        hasUnsavedLayoutChanges: [
            (s) => [s.dashboard, s.dashboardLayouts],
            (
                dashboard: DashboardType<QueryBasedInsightModel> | null,
                dashboardLayouts: Record<DashboardTile['id'], DashboardTile['layouts']>
            ): boolean => {
                if (!dashboard) {
                    return false
                }
                return (dashboard.tiles || []).some((tile: DashboardTile<QueryBasedInsightModel>) => {
                    const originalSm = dashboardLayouts?.[tile.id]?.sm
                    const currentSm = tile.layouts?.sm
                    return !equal(originalSm || {}, currentSm || {})
                })
            },
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

                const usedVariables = dataVizNodes.flatMap((n) =>
                    filterVariablesReferencedInQuery(
                        n.query.source.query,
                        Object.values(n.query.source.variables ?? {})
                    )
                )
                const uniqueVariables = uniqBy(usedVariables, (n) => n.variableId)

                const effectiveVariables = uniqueVariables
                    .map((v) => {
                        const variable = variables.find((n) => n.id === v.variableId)
                        const urlVariable = urlVariables[v.variableId]

                        if (!variable) {
                            return null
                        }

                        const dashboardVariable = dashboard.persisted_variables?.[v.variableId]
                        const variableSources = [urlVariable, dashboardVariable, v]
                        const valueSource = variableSources.find((source) =>
                            source ? Object.prototype.hasOwnProperty.call(source, 'value') : false
                        )
                        const isNullSource = variableSources.find((source) =>
                            source ? Object.prototype.hasOwnProperty.call(source, 'isNull') : false
                        )

                        // determine effective variable state
                        const resultVar: Variable = {
                            ...variable,
                            value: valueSource ? valueSource.value : variable.default_value,
                            isNull: isNullSource ? isNullSource.isNull : variable.isNull,
                        }

                        // get insights using variable
                        const insightsUsingVariable = dataVizNodes
                            .filter((n) => {
                                return filterVariablesReferencedInQuery(
                                    n.query.source.query,
                                    Object.values(n.query.source.variables ?? {})
                                ).some((variable) => variable.variableId === v.variableId)
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
            (dashboard: DashboardType): DashboardTemplateEditorType | undefined =>
                dashboardToSaveableTemplate(dashboard),
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
        widgetTiles: [(s) => [s.tiles], (tiles) => tiles.filter((t) => !!t.widget)],
        dashboardWidgetsEnabled: [
            (s) => [s.featureFlags, s.tiles, s.placement],
            (featureFlags, tiles, placement): boolean => {
                // Shared dashboards don't receive team feature flags; render widget tiles when
                // metadata is already present on the exported dashboard payload.
                if (placement === DashboardPlacement.Public && tiles.some((tile) => !!tile.widget)) {
                    return true
                }
                return !!featureFlags[FEATURE_FLAGS.DASHBOARD_WIDGETS]
            },
        ],
        inlineTileInsertionEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.DASHBOARD_INLINE_TILE_INSERTION],
        ],
        insightTiles: [
            (s) => [s.tiles],
            (tiles) => tiles.filter((t) => !!t.insight).filter((i) => !i.insight?.deleted),
        ],
        textTiles: [(s) => [s.tiles], (tiles) => tiles.filter((t) => !!t.text)],
        itemsLoading: [
            (s) => [
                s.dashboardLoading,
                s.dashboardStreaming,
                s.refreshStatus,
                s.initialVariablesLoaded,
                s.initialQuickFiltersLoaded,
                s.dashboardFiltersEnabled,
            ],
            (
                dashboardLoading,
                dashboardStreaming,
                refreshStatus,
                initialVariablesLoaded,
                initialQuickFiltersLoaded,
                dashboardFiltersEnabled
            ) => {
                return (
                    dashboardLoading ||
                    dashboardStreaming ||
                    Object.values(refreshStatus).some((s) => s.loading || s.queued) ||
                    (SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams && !initialVariablesLoaded) ||
                    ('quick_filters' in router.values.searchParams &&
                        dashboardFiltersEnabled &&
                        !initialQuickFiltersLoaded)
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
                // Pessimistic: the banner must not claim the dashboard is fresher than the stalest insight
                // tile (per-tile menus use insight.last_refresh). `last_dashboard.last_refresh` and client
                // `updateDashboardLastRefresh(dayjs())` can otherwise run ahead of embedded tile metadata.
                return oldestRefreshed ?? lastDashboardRefresh ?? null
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
        dashboardFiltersEnabled: [
            (s) => [s.placement, s.featureFlags],
            (placement: DashboardPlacement, featureFlags: Record<string, string | boolean>): boolean => {
                const excludedPlacements = [
                    DashboardPlacement.Public,
                    DashboardPlacement.Export,
                    DashboardPlacement.FeatureFlag,
                    DashboardPlacement.Group,
                    DashboardPlacement.Builtin,
                ]
                if (excludedPlacements.includes(placement)) {
                    return false
                }
                return featureFlags[FEATURE_FLAGS.DASHBOARD_QUICK_FILTERS_EXPERIMENT] === 'test'
            },
        ],
        totalAdvancedFilters: [
            (s) => [s.effectiveEditBarFilters],
            (effectiveEditBarFilters: DashboardFilter): number => {
                const propertyFiltersCount = effectiveEditBarFilters.properties?.length || 0
                const hasBreakdown = !!(
                    effectiveEditBarFilters.breakdown_filter?.breakdown_type ||
                    effectiveEditBarFilters.breakdown_filter?.breakdowns?.length
                )
                return propertyFiltersCount + (hasBreakdown ? 1 : 0)
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
        /** Save-as-project-template from dashboard scene: editor on dashboard and payload has tiles. Staff use the same modal, with an optional JSON editor entry inside. */
        canSaveProjectDashboardTemplate: [
            (s) => [s.canEditDashboard, s.asDashboardTemplate],
            (canEditDashboard, asDashboardTemplate): boolean =>
                canEditDashboard && !!(asDashboardTemplate?.tiles?.length ?? 0),
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
            (tiles) => calculateLayouts(tiles),
            // Tile refreshes replace `tiles` once per insight response without touching geometry;
            // keeping the result reference stable stops react-grid-layout re-laying-out every tile
            // N times per dashboard refresh cycle.
            { resultEqualityCheck: objectsEqual },
        ],
        layout: [
            (s) => [s.layouts, s.sizeKey],
            (layouts: ResponsiveLayouts, sizeKey: DashboardLayoutSize | undefined) =>
                sizeKey ? layouts[sizeKey] : undefined,
        ],
        layoutForItem: [
            (s) => [s.layout],
            (layout: TileLayout[] | undefined) => {
                const layoutForItem: Record<string, TileLayout> = {}
                if (layout) {
                    for (const obj of layout) {
                        if (obj.i) {
                            layoutForItem[obj.i] = obj
                        }
                    }
                }
                return layoutForItem
            },
        ],
        refreshMetrics: [
            (s) => [s.refreshStatus, s.refreshTilesTotal],
            (refreshStatus, refreshTilesTotal) => {
                const inFlight = Object.values(refreshStatus).filter((s) => s.loading || s.queued).length
                // Pinned batch size keeps Y fixed for the cycle; fall back to the live map for single-insight refreshes.
                const total = refreshTilesTotal ?? Object.keys(refreshStatus).length
                return {
                    completed: total - inFlight,
                    total,
                }
            },
        ],
        breadcrumbs: [
            (s) => [s.dashboard, s.error404, s.dashboardFailedToLoad, router.selectors.searchParams],
            (
                dashboard: DashboardType<QueryBasedInsightModel> | null,
                error404: boolean,
                dashboardFailedToLoad: boolean,
                searchParams: Record<string, any>
            ): Breadcrumb[] => {
                const backUrl = searchParams.backUrl as string | undefined
                const backName = searchParams.backName as string | undefined
                return [
                    backUrl
                        ? {
                              key: backUrl,
                              name: backName || 'Back',
                              path: backUrl,
                              iconType: 'dashboard',
                          }
                        : {
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
    events(({ actions, props, values, cache }) => ({
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
                    const hasVariablesInUrl = SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams
                    const hasQuickFiltersInUrl =
                        'quick_filters' in router.values.searchParams && values.dashboardFiltersEnabled

                    if (!hasVariablesInUrl && !hasQuickFiltersInUrl) {
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
                    // Deferred — quick filters wait for quickFiltersUrlRestoreComplete,
                    // variables wait for loadVariablesSuccess. Explicitly trigger
                    // the variable fetch to ensure variables are loaded before
                    // the dashboard loads.
                    if (hasVariablesInUrl) {
                        variableDataLogic.actions.loadVariables()
                    } else {
                        // No URL variables to wait for — mark as loaded so the
                        // urlVariables selector is active for runtime overrides
                        // (e.g. when users change variable values on the dashboard).
                        actions.setInitialVariablesLoaded(true)
                    }
                }
            }
        },
        beforeUnmount: () => {
            cache.widgetTileRefreshScheduler?.cancelAll()
            actions.abortAnyRunningQuery()
            // Bound the inline-insertion target's lifetime to this mount, so a never-consumed target
            // (e.g. an add flow abandoned by navigating away) can't reposition a tile on a later visit.
            cache.tileIdsBeforeInsertion = undefined
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
        scheduleRefreshDashboardWidgets: ({ tileId }: { tileId: number }) => {
            if (!cache.widgetTileRefreshScheduler) {
                cache.widgetTileRefreshScheduler = createDashboardWidgetTileRefreshScheduler((id) =>
                    actions.refreshDashboardWidgets({ tileIds: [id], forceRefresh: true })
                )
            }
            cache.widgetTileRefreshScheduler.schedule(tileId)
        },
        setAddWidgetModalOpen: ({ open }) => {
            if (open) {
                actions.clearAddWidgetSelectedTypes()
            }
        },
        togglePinned: () => {
            if (values.dashboard) {
                // Reducers have already run, so values.isPinned reflects the desired new state.
                if (values.isPinned) {
                    dashboardsModel.actions.pinDashboard(values.dashboard.id, DashboardEventSource.SceneCommonButtons)
                } else {
                    dashboardsModel.actions.unpinDashboard(values.dashboard.id, DashboardEventSource.SceneCommonButtons)
                }
            }
        },
        updateTileColor: async ({ tileId, color }) => {
            // Defense in depth: shared dashboards (DashboardPlacement.Public)
            // shouldn't render the tile-color editor, so this listener should
            // never fire from shared mode. Guarding here avoids a phantom
            // optimistic local state change that reverts on the inevitable 401.
            if (isSharedView()) {
                return
            }
            const previousColor = values.tiles.find((tile) => tile.id === tileId)?.color
            actions.setTileProperty(tileId, { color })
            try {
                await api.update(`api/environments/${values.currentTeamId}/dashboards/${props.id}`, {
                    tiles: [{ id: tileId, color }],
                })
            } catch {
                actions.setTileProperty(tileId, { color: previousColor })
                lemonToast.error('Failed to update tile color')
            }
        },
        toggleTileDescription: async ({ tileId }) => {
            // Defense in depth — same reason as updateTileColor above.
            if (isSharedView()) {
                return
            }
            const matchingTile = values.tiles.find((tile) => tile.id === tileId)
            const previousValue = matchingTile?.show_description
            const newValue = previousValue === false
            actions.setTileProperty(tileId, { show_description: newValue })
            try {
                await api.update(`api/environments/${values.currentTeamId}/dashboards/${props.id}`, {
                    tiles: [{ id: tileId, show_description: newValue }],
                })
            } catch {
                actions.setTileProperty(tileId, { show_description: previousValue })
                lemonToast.error('Failed to update tile')
            }
        },
        setRefreshError: sharedListeners.reportRefreshTiming,
        setRefreshStatuses: sharedListeners.reportRefreshTiming,
        setRefreshStatus: sharedListeners.reportRefreshTiming,
        setPageVisibility: ({ visible }) => {
            if (!visible) {
                cache.disposables.dispose('autoRefreshInterval')
            } else if (values.autoRefresh.enabled) {
                actions.resetInterval()
            }
        },
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
        [dashboardsModel.actionTypes.updateDashboard]: ({ id, tiles }) => {
            // Render newly-created text tiles right away; the save response replaces them, failure rolls them back.
            if (id !== props.id || !Array.isArray(tiles)) {
                return
            }
            const newTextTiles = tiles.filter((tile) => !!tile?.text && tile?.id == null)
            if (!newTextTiles.length) {
                return
            }
            const optimisticTiles = newTextTiles.map((tile) => {
                // Negative id marks the tile as optimistic until the server response replaces it.
                cache.nextOptimisticTileId = (cache.nextOptimisticTileId ?? 0) - 1
                return {
                    id: cache.nextOptimisticTileId,
                    text: tile.text,
                    transparent_background: tile.transparent_background,
                    layouts: tile.layouts || {},
                    color: null,
                } as DashboardTile<QueryBasedInsightModel>
            })
            actions.addOptimisticTiles(optimisticTiles)
        },
        [dashboardsModel.actionTypes.updateDashboardFailure]: () => {
            actions.removeOptimisticTiles()
        },
        setPendingInsertion: ({ pendingInsertion }) => {
            // Snapshot current tile ids so we can identify the tile the add flow appends afterwards.
            cache.tileIdsBeforeInsertion = pendingInsertion ? new Set((values.tiles || []).map((t) => t.id)) : undefined
        },
        applyPendingInsertion: async () => {
            // Capture before setPendingInsertion(null) below clears it.
            const slot = values.pendingInsertion
            const previousTileIds = cache.tileIdsBeforeInsertion as Set<number> | undefined
            if (!slot || !previousTileIds) {
                return
            }

            // Load-bearing assumption: exactly one unknown tile appeared since the snapshot and it is the
            // one the add flow just created. A concurrent arrival (background refresh, a collaborator's add)
            // in this window could be mis-targeted — blast radius is one tile's layout, which we accept.
            const newTile = (values.tiles || []).find((tile) => !tile.deleted && !previousTileIds.has(tile.id))
            if (!newTile) {
                // The appended tile hasn't reached state yet; a later arrival signal will retry.
                return
            }

            // Clear before persisting so the resulting updateDashboardSuccess doesn't re-enter this listener.
            actions.setPendingInsertion(null)

            const smLayout = values.layouts?.sm
            const newTileLayoutEntry = smLayout?.find((l) => String(l.i) === String(newTile.id))
            const w = slot.w ?? newTileLayoutEntry?.w ?? DEFAULT_INSERTED_TILE_SIZE.w
            const h = newTileLayoutEntry?.h ?? DEFAULT_INSERTED_TILE_SIZE.h

            // Text/widget tiles are created at the slot, so only the tiles they displace need moving.
            // Insights arrive with no layout (added via a reload) and still need positioning here.
            const newTileAlreadyAtSlot = newTileLayoutEntry?.x === slot.x && newTileLayoutEntry?.y === slot.y

            const { newTileLayout, tilesToUpdate } = calculateInsertionLayout(
                smLayout,
                newTile.id,
                slot.y,
                slot.x,
                w,
                h
            )

            // The inline insert has landed at the line — report it (outcome, vs the option-clicked intent).
            const insertedTileType = newTile.text
                ? 'text_card'
                : newTile.button_tile
                  ? 'button'
                  : newTile.widget
                    ? 'widget'
                    : 'insight'
            eventUsageLogic.actions.reportDashboardTileInsertedInline(insertedTileType, slot.x, slot.y, slot.w != null)

            // Already at the slot with nothing to displace — the created position stands, no follow-up needed.
            if (newTileAlreadyAtSlot && tilesToUpdate.length === 0) {
                return
            }

            // Apply optimistically so the grid reflows immediately.
            const shiftById = new Map(tilesToUpdate.map((t) => [t.id, t.layouts.sm]))
            const newSmLayout = (smLayout || []).map((l) => {
                if (!newTileAlreadyAtSlot && String(l.i) === String(newTile.id)) {
                    return { ...l, ...newTileLayout.sm }
                }
                const shifted = shiftById.get(parseInt(l.i))
                return shifted ? { ...l, ...shifted } : l
            })
            actions.updateLayouts({ ...values.layouts, sm: newSmLayout })

            // In edit mode the change is saved with the rest of the edit session.
            if (values.layoutEditMode) {
                return
            }

            // Persist the reflow (same raw-PATCH shape as duplicateTile / saveEditModeChanges). The new tile's
            // own layout only rides along when we had to place it (insights); text/widget tiles already carry it.
            const tilesToPersist = newTileAlreadyAtSlot
                ? tilesToUpdate
                : [...tilesToUpdate, { id: newTile.id, layouts: newTileLayout }]
            try {
                const response: DashboardType<InsightModel> = await api.update(
                    `api/environments/${values.currentTeamId}/dashboards/${props.id}`,
                    {
                        tiles: tilesToPersist,
                    }
                )
                const updated = getQueryBasedDashboard(response)
                if (updated) {
                    dashboardsModel.actions.updateDashboardSuccess(updated)
                }
            } catch (e) {
                lemonToast.error('Could not position the new tile: ' + String(e))
            }
        },
        [dashboardsModel.actionTypes.updateDashboardSuccess]: ({ dashboard }) => {
            // Text/button (via updateDashboard) and widget (client-merged) tiles arrive through here.
            if (dashboard?.id === props.id) {
                actions.applyPendingInsertion()
            }
        },
        [dashboardsModel.actionTypes.updateDashboardInsight]: ({ insight, extraDashboardIds, sourceDashboardId }) => {
            if (sourceDashboardId != null && sourceDashboardId !== props.id) {
                // Same rationale as the reducer: ignore refresh payloads scoped to another dashboard.
                return
            }
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
        duplicateTile: () => {
            cache.widgetTileIdsBeforeDuplicate = new Set(values.widgetTiles.map((tile) => tile.id))
        },
        duplicateTileSuccess: ({ dashboard }) => {
            if (!dashboard || !values.dashboardWidgetsEnabled) {
                return
            }

            const previousTileIds = cache.widgetTileIdsBeforeDuplicate as Set<number> | undefined
            cache.widgetTileIdsBeforeDuplicate = undefined
            if (!previousTileIds) {
                return
            }

            const createdTiles = findNewlyAddedWidgetTiles(previousTileIds, dashboard.tiles)
            if (createdTiles.length > 0) {
                actions.refreshDashboardWidgets({
                    tileIds: createdTiles.map((tile) => tile.id),
                    forceRefresh: true,
                })
            }
        },
        removeTile: ({ tile }) => {
            cache.removedTileForUndo = tile
        },
        removeTileSuccess: () => {
            const tile = cache.removedTileForUndo as DashboardTile<QueryBasedInsightModel> | undefined
            cache.removedTileForUndo = undefined
            if (!tile) {
                return
            }

            const tileName = getDashboardTileDisplayName(tile)
            const isWidgetTile = !!tile.widget
            const removedMessage = isWidgetTile ? 'widget removed' : 'has been removed from the dashboard'
            const toastId = `remove-tile-${tile.id}`

            lemonToast.info(
                <>
                    <b>{tileName}</b> {removedMessage}
                </>,
                {
                    toastId,
                    button: {
                        label: 'Undo',
                        dataAttr: 'undo-remove-tile-from-dashboard',
                        action: async () => {
                            try {
                                await api.update(`api/environments/${values.currentTeamId}/dashboards/${props.id}`, {
                                    tiles: [{ id: tile.id, deleted: false }],
                                })

                                if (tile.insight) {
                                    const insight = tile.insight
                                    const nextDashboards = insight.dashboards?.includes(props.id)
                                        ? insight.dashboards
                                        : [...(insight.dashboards || []), props.id]
                                    dashboardsModel.actions.updateDashboardInsight(
                                        { ...insight, dashboards: nextDashboards },
                                        [props.id]
                                    )
                                }

                                actions.loadDashboard({ action: DashboardLoadAction.Update })

                                lemonToast.success(
                                    <>
                                        <b>{tileName}</b> {isWidgetTile ? 'widget restored' : 'has been restored'}
                                    </>,
                                    { toastId }
                                )
                            } catch (e) {
                                lemonToast.error('Could not restore tile: ' + String(e))
                            }
                        },
                    },
                }
            )
        },
        moveToDashboardSuccess: ({ payload }) => {
            if (payload?.toDashboard === undefined || payload?.tile === undefined) {
                return
            }

            const { tile, fromDashboard, toDashboard, toDashboardName } = payload
            const updatedTile: DashboardTile<QueryBasedInsightModel> = { ...tile }

            const nextTilePlacement = (
                existing: DashboardTileBasicType[] | null | undefined
            ): DashboardTileBasicType[] => [
                ...(existing || []).filter((t) => t.dashboard_id !== fromDashboard),
                { id: tile.id, dashboard_id: toDashboard },
            ]

            if (updatedTile.insight) {
                const ins = updatedTile.insight
                const nextDashboardTiles = nextTilePlacement(ins.dashboard_tiles ?? undefined)
                const nextDashboards = [...(ins.dashboards?.filter((d) => d !== fromDashboard) || []), toDashboard]
                updatedTile.insight = {
                    ...ins,
                    dashboards: nextDashboards,
                    dashboard_tiles: nextDashboardTiles,
                }
                dashboardsModel.actions.updateDashboardInsight(updatedTile.insight, [toDashboard])
            }

            if (updatedTile.text) {
                const txt = updatedTile.text
                updatedTile.text = {
                    ...txt,
                    dashboard_tiles: nextTilePlacement(txt.dashboard_tiles ?? undefined),
                }
            }

            if (updatedTile.button_tile) {
                const btn = updatedTile.button_tile
                updatedTile.button_tile = {
                    ...btn,
                    dashboard_tiles: nextTilePlacement(btn.dashboard_tiles ?? undefined),
                }
            }

            if (updatedTile.widget) {
                const widget = updatedTile.widget
                updatedTile.widget = {
                    ...widget,
                    dashboard_tiles: nextTilePlacement(widget.dashboard_tiles ?? undefined),
                }
            }

            dashboardsModel.actions.tileMovedToDashboard(updatedTile, toDashboard)

            const moveToastLabel: Record<DashboardWidgetType, string> = {
                insight: 'Insight',
                text: 'Text card',
                button_tile: 'Button',
                widget: 'Widget',
            }
            const movedWidgetType = getDashboardWidgetType(updatedTile)

            lemonToast.success(
                <>
                    {moveToastLabel[movedWidgetType]} moved to{' '}
                    <b>
                        <Link to={urls.dashboard(toDashboard)}>{toDashboardName}</Link>
                    </b>
                </>
                // TODO implement undo for move to dashboard
            )
        },
        triggerDashboardUpdate: ({ payload }) => {
            if (values.dashboard) {
                dashboardsModel.actions.updateDashboard({ id: values.dashboard.id, ...payload })
            }
        },
        forceRefreshIfStale: () => {
            // Dedupe: this listener can be invoked from multiple sources for the same
            // freshness state — the post-load auto-trigger in refreshDashboardItems and
            // the visibility-change callback in ExporterDashboardScene can both fire on
            // the same render tick. Tracking the last `effectiveLastRefresh` we already
            // forced a refresh against ensures we queue at most one trigger per
            // freshness window. Once a refresh lands, `effectiveLastRefresh` advances
            // and a future stale window can re-fire.
            const currentRefreshKey = values.effectiveLastRefresh?.valueOf() ?? null
            if (cache.lastAutoForcedFor === currentRefreshKey) {
                return
            }
            if (!shouldSharedDashboardAutoForceForStaleTime(values.effectiveLastRefresh)) {
                return
            }
            cache.lastAutoForcedFor = currentRefreshKey
            queueMicrotask(() => {
                void actions.triggerDashboardRefresh()
            })
        },
        /** Triggered from dashboard refresh button, when user refreshes entire dashboard */
        triggerDashboardRefresh: () => {
            actions.resetInterval()
            actions.refreshDashboardItems({ action: RefreshDashboardItemsAction.Refresh, forceRefresh: true })
            if (
                values.dashboardWidgetsEnabled &&
                values.placement !== DashboardPlacement.Export &&
                values.placement !== DashboardPlacement.Public
            ) {
                const widgetTileIds = values.widgetTiles.map((tile) => tile.id)
                if (widgetTileIds.length > 0) {
                    actions.refreshDashboardWidgets({ tileIds: widgetTileIds, forceRefresh: true })
                }
            }
        },
        /** Called when a single insight is refreshed manually on the dashboard */
        refreshDashboardItem: async ({ tile }, breakpoint) => {
            const dashboardId: number = props.id
            const insight = tile.insight

            if (!insight) {
                return
            }

            // Shared/public/export viewers must not be able to trigger server-side refreshes.
            if (isSharedView()) {
                return
            }

            // Cache values before the long-running await — the logic may unmount
            const { currentTeamId, effectiveRefreshFilters, urlFilters, urlVariables } = values

            actions.setRefreshStatus(insight.short_id, true, true)

            try {
                breakpoint()

                const refreshStartTime = performance.now()
                // when one insight is refreshed manually, we want to avoid cache and force a refresh of the insight
                // hence using 'force_blocking', small cost to give latest data for the insight
                // also it's then consistent with the dashboard refresh button
                const refreshedInsight = await getInsightWithRetry(
                    currentTeamId,
                    insight,
                    dashboardId,
                    uuid(),
                    'force_blocking',
                    undefined,
                    effectiveRefreshFilters,
                    urlVariables,
                    tile.filters_overrides
                )

                eventUsageLogic.actions.reportDashboardTileRefreshed(
                    dashboardId,
                    tile,
                    urlFilters,
                    urlVariables,
                    Math.floor(performance.now() - refreshStartTime),
                    true
                )

                if (refreshedInsight) {
                    dashboardsModel.actions.updateDashboardInsight(refreshedInsight, undefined, dashboardId)
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
            let tilesRefreshedCachedCount = 0
            let tilesErroredCount = 0
            let tilesAbortedCount = 0

            if (sortedTilesToRefresh.length > 0) {
                await breakpoint()
                actions.resetIntermittentFilters()

                // Pin the progress denominator to the batch size before enrolling the insights
                actions.setRefreshTilesTotal(tilesStaleCount)
                // Set refresh status for all insights
                actions.setRefreshStatuses(
                    sortedTilesToRefresh.map((tile) => tile.insight.short_id),
                    false,
                    true
                )

                actions.abortAnyRunningQuery()
                cache.abortController = new AbortController()
                const methodOptions: ApiMethodOptions = { signal: cache.abortController.signal }

                // Cache values used during and after the long-running fetch, since the logic
                // may be unmounted by the time the awaits complete (kea's no-arg breakpoint()
                // only cancels on newer invocations, not on unmount).
                const {
                    currentTeamId,
                    effectiveRefreshFilters,
                    urlFilters,
                    urlVariables,
                    dashboardLoadData,
                    dashboard,
                    lastDashboardRefresh,
                } = values

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
                            currentTeamId,
                            insight,
                            dashboardId,
                            queryId,
                            forceRefresh ? 'force_blocking' : 'blocking', // 'blocking' returns cached data if available, when manual refresh is triggered we want fresh results
                            methodOptions,
                            effectiveRefreshFilters,
                            urlVariables,
                            tile.filters_overrides
                        )

                        if (refreshedInsight) {
                            dashboardsModel.actions.updateDashboardInsight(refreshedInsight, undefined, dashboardId)
                            actions.setRefreshStatus(insight.short_id)
                            tilesRefreshedCount++
                            if (refreshedInsight.is_cached) {
                                tilesRefreshedCachedCount++
                            }

                            eventUsageLogic.actions.reportDashboardTileRefreshed(
                                dashboardId,
                                tile,
                                urlFilters,
                                urlVariables,
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
                            actions.abortQuery({ queryId, queryStartTime, shortId: insight.short_id })
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
                // and all tiles were refreshed
                if (forceRefresh && tilesAbortedCount === 0 && tilesErroredCount === 0) {
                    actions.updateDashboardLastRefresh(dayjs())
                }

                if (isInitialLoad) {
                    // capture time to see data
                    const { dashboardQueryId, startTime, responseBytes } = dashboardLoadData
                    eventUsageLogic.actions.reportTimeToSeeData({
                        team_id: currentTeamId,
                        type: 'dashboard_load',
                        context: 'dashboard',
                        action,
                        status: 'success',
                        primary_interaction_id: dashboardQueryId,
                        time_to_see_data_ms: Math.floor(performance.now() - startTime),
                        api_response_bytes: responseBytes,
                        insights_fetched: sortedTilesToRefresh.length,
                        insights_fetched_cached: tilesRefreshedCachedCount,
                        ...getJSHeapMemory(),
                    })
                }

                eventUsageLogic.actions.reportDashboardRefreshed(
                    dashboardId,
                    dashboard,
                    urlFilters,
                    urlVariables,
                    lastDashboardRefresh,
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

            if (
                isInitialLoad &&
                !forceRefresh &&
                tilesErroredCount === 0 &&
                tilesAbortedCount === 0 &&
                values.placement === DashboardPlacement.Public
            ) {
                actions.forceRefreshIfStale()
            }

            if (
                values.dashboardWidgetsEnabled &&
                values.placement !== DashboardPlacement.Export &&
                values.placement !== DashboardPlacement.Public
            ) {
                const widgetTileIds = values.widgetTiles.map((tile) => tile.id)
                if (widgetTileIds.length > 0) {
                    actions.refreshDashboardWidgets({ tileIds: widgetTileIds, forceRefresh: !!forceRefresh })
                }
            }
        },
        refreshDashboardWidgets: async ({ tileIds, forceRefresh }, breakpoint) => {
            if (
                values.placement === DashboardPlacement.Export ||
                values.placement === DashboardPlacement.Public ||
                !values.dashboardWidgetsEnabled
            ) {
                return
            }

            const staleTileIds = tileIds.filter((tileId) => {
                if (forceRefresh) {
                    return true
                }
                const fetchedAt = values.widgetRefreshStatus[tileId]?.fetchedAt
                return !fetchedAt || Date.now() - fetchedAt > WIDGET_CLIENT_TTL_MS
            })

            if (staleTileIds.length === 0) {
                return
            }

            actions.setWidgetRefreshStatuses(staleTileIds, true)
            await breakpoint()

            const projectId = String(values.currentTeamId)
            const dashboardId = props.id
            const fetchFunctions = chunkTileIds(staleTileIds, 4).map((chunk) => async () => {
                try {
                    const results = await fetchRunWidgets(projectId, dashboardId, chunk, {
                        signal: cache.abortController?.signal,
                    })
                    const resultsByTileId = Object.fromEntries(results.map((result) => [result.tile_id, result]))
                    actions.setWidgetRunResults(resultsByTileId)
                    for (const result of results) {
                        actions.setWidgetRefreshStatuses(
                            [result.tile_id],
                            false,
                            result.error ? DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE : null
                        )
                    }
                } catch {
                    actions.setWidgetRefreshStatuses(chunk, false, DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE)
                }
            })

            await runWithLimit(fetchFunctions, 4)
        },
        addWidgetTiles: async ({ dashboardId, widgets }) => {
            if (widgets.length === 0) {
                return
            }

            try {
                const previousWidgetTileIds = new Set(values.widgetTiles.map((tile) => tile.id))

                // Inline insertion: create the widget at the chosen slot instead of the backend's
                // default bottom placement, and let applyPendingInsertion shift existing tiles down.
                // Only single-widget adds insert positionally — applyPendingInsertion repositions one
                // tile, so a multi-select add can't be cleanly inserted at a single slot; it appends.
                if (values.pendingInsertion && widgets.length !== 1) {
                    actions.setPendingInsertion(null)
                }
                const insertSlot = widgets.length === 1 ? values.pendingInsertion : null
                const widgetsPayload = widgets.map(({ widgetType, config }) => {
                    if (!insertSlot) {
                        return { widget_type: widgetType, config }
                    }
                    const defaultLayout =
                        widgetType in DASHBOARD_WIDGET_CATALOG
                            ? getDashboardWidgetCatalogEntry(widgetType).defaultLayout
                            : undefined
                    const w = insertSlot.w ?? defaultLayout?.w ?? DEFAULT_INSERTED_TILE_SIZE.w
                    const h = defaultLayout?.h ?? DEFAULT_INSERTED_TILE_SIZE.h
                    return {
                        widget_type: widgetType,
                        config,
                        layouts: { sm: { x: insertSlot.x, y: insertSlot.y, w, h } },
                    }
                })

                const response = await api.create(
                    `api/environments/${teamLogic.values.currentTeamId}/dashboards/${dashboardId}/widgets/batch/`,
                    { widgets: widgetsPayload }
                )
                const createdTiles = findNewlyAddedWidgetTiles(previousWidgetTileIds, response.tiles)
                if (createdTiles.length > 0 && values.dashboard?.id === dashboardId) {
                    const dashboard = getQueryBasedDashboard({
                        ...values.dashboard,
                        tiles: [...values.dashboard.tiles, ...createdTiles],
                    } as DashboardType<InsightModel>)
                    if (dashboard) {
                        dashboardsModel.actions.updateDashboardSuccess(dashboard)

                        // Only auto-scroll when the new tiles actually went to the bottom.
                        if (!insertSlot) {
                            actions.requestScrollToBottom()
                        }
                    }
                }

                if (createdTiles.length > 0) {
                    actions.refreshDashboardWidgets({
                        tileIds: createdTiles.map((tile) => tile.id),
                        forceRefresh: true,
                    })
                }

                const count = createdTiles.length
                if (count > 1) {
                    lemonToast.success(`Added ${count} widgets`)
                }
            } catch (e) {
                lemonToast.error(e instanceof ApiError ? (e.detail ?? e.message) : 'Could not add widgets')
                throw e
            } finally {
                actions.addWidgetTileFinished()
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
        saveEditModeChangesSuccess: ({ dashboard }) => {
            if (dashboard) {
                // Sync the saved dashboard (including any name/description changes) to
                // dashboardsModel so the sidebar and other global views stay up to date
                dashboardsModel.actions.updateDashboardSuccess(dashboard)
            }
            // Only toast when changes were actually persisted — the no-op exit path skips the PATCH.
            if (cache.dashboardChangesPersisted) {
                cache.dashboardChangesPersisted = false
                lemonToast.success('Dashboard saved')
            }
            if (cache.shouldRefreshTilesAfterSave) {
                cache.shouldRefreshTilesAfterSave = false
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        cancelEditMode: () => {
            const discard = (): void =>
                actions.setDashboardMode(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            const promptEnabled = !!values.featureFlags[FEATURE_FLAGS.DASHBOARD_LAYOUT_DISCARD_PROMPT]
            if (!promptEnabled || !values.hasUnsavedLayoutChanges) {
                discard()
                return
            }
            eventUsageLogic.actions.reportDashboardEditModeDiscardPrompt(values.dashboard, 'shown')
            LemonDialog.open({
                title: 'Discard layout changes?',
                description:
                    'You have moved tiles around but not saved. If you discard now, the layout will revert to its last saved state.',
                primaryButton: {
                    children: 'Discard changes',
                    status: 'danger',
                    onClick: () => {
                        eventUsageLogic.actions.reportDashboardEditModeDiscardPrompt(values.dashboard, 'discarded')
                        discard()
                    },
                    'data-attr': 'dashboard-edit-mode-discard-confirm',
                },
                secondaryButton: {
                    children: 'Keep editing',
                    onClick: () => {
                        eventUsageLogic.actions.reportDashboardEditModeDiscardPrompt(values.dashboard, 'kept_editing')
                    },
                },
            })
        },
        setDashboardMode: async ({ mode, source }) => {
            if (
                mode === DashboardMode.Edit &&
                values.urlSearchParamsAtEditModeEntry === null &&
                shouldSnapshotUrlAtEditModeEntry(source)
            ) {
                const encodedFilters = encodeURLFilters(values.urlFilters)
                actions.setUrlSearchParamsAtEditModeEntry({
                    filters: encodedFilters[SEARCH_PARAM_FILTERS_KEY],
                    variables: router.values.searchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY],
                })
            }

            if (
                mode === DashboardMode.Edit &&
                source !== DashboardEventSource.DashboardHeaderDiscardChanges &&
                isLayoutEditEventSource(source)
            ) {
                clearDOMTextSelection()
                lemonToast.info('Now editing the dashboard – press E or click Save to persist changes')
            } else if (source === DashboardEventSource.DashboardHeaderDiscardChanges) {
                // reset filters to that before previewing
                actions.resetIntermittentFilters()
                actions.restoreUrlStateAtEditModeEntry(values.urlSearchParamsAtEditModeEntry)

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
                    source === DashboardEventSource.SceneCommonButtons)
            ) {
                // save edit mode changes when exiting via Save button or E key/Edit layout button
                // Pending name/description are included in the saveEditModeChanges PATCH
                // to avoid a race between two concurrent PATCHes to the same endpoint.
                actions.saveEditModeChanges()
            }

            if (mode || source) {
                const isFilterOnlyEditEntry =
                    mode === DashboardMode.Edit && source !== null && !isLayoutEditEventSource(source)

                if (mode === DashboardMode.Edit && source !== null && isLayoutEditEventSource(source)) {
                    eventUsageLogic.actions.reportDashboardLayoutEditModeEntered(
                        values.dashboard,
                        source,
                        values.layoutEditMode ? values.layoutZoom : null
                    )
                }

                if (!isFilterOnlyEditEntry) {
                    eventUsageLogic.actions.reportDashboardModeToggled(
                        values.dashboard,
                        mode,
                        source,
                        values.layoutEditMode ? values.layoutZoom : null,
                        values.layoutEditMode
                    )
                }
            }

            if (mode !== DashboardMode.Edit) {
                actions.setLayoutZoom(1)
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
                // Insight tiles arrive via a dashboard reload; reposition to the pending insertion row.
                actions.applyPendingInsertion()
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

            if (insightIds.length > 0 && values.currentTeamId && !isSharedView()) {
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
        cancelDashboardRefresh: () => {
            actions.abortAnyRunningQuery()
        },
        abortQuery: async ({ queryId, queryStartTime }) => {
            const { currentTeamId, dashboardLoadData } = values
            try {
                await api.insights.cancelQuery(queryId, currentTeamId ?? undefined)
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }

            const { dashboardQueryId } = dashboardLoadData
            eventUsageLogic.actions.reportTimeToSeeData({
                team_id: currentTeamId,
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
        setProperties: ({ properties }) => {
            eventUsageLogic.actions.reportDashboardFiltersChanged(values.dashboard, 'properties', {
                property_count: properties?.length ?? 0,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        setDates: ({ date_from, date_to }) => {
            eventUsageLogic.actions.reportDashboardFiltersChanged(values.dashboard, 'date', {
                date_from,
                date_to: date_to ?? null,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        setBreakdownFilter: ({ breakdown_filter }) => {
            eventUsageLogic.actions.reportDashboardFiltersChanged(values.dashboard, 'breakdown', {
                breakdown_type: breakdown_filter?.breakdown_type ?? null,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        setExternalFilters: () => {
            if (values.tiles.length > 0) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                })
            }
        },
        overrideVariableValue: ({ variableId }) => {
            eventUsageLogic.actions.reportDashboardFiltersChanged(values.dashboard, 'variable', {
                variable_id: variableId,
            })

            actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Preview,
                forceRefresh: false,
            })
            if (values.dashboardMode !== DashboardMode.Edit) {
                actions.setDashboardMode(DashboardMode.Edit, DashboardEventSource.DashboardVariableOverride)
            }
        },
        quickFiltersCommitted: async (_, breakpoint) => {
            // Only handle quick filter commits for dashboard placements — embedded placements
            // (FeatureFlag, Group, etc.) mount dashboardLogic but don't use quick filters
            if (values.placement !== DashboardPlacement.Dashboard) {
                return
            }

            // Only refresh when the quick filters experiment is active for this user
            if (!values.dashboardFiltersEnabled) {
                return
            }

            // Cache values before breakpoint — they may change during the debounce window
            const visibleFilterCount = values.dashboard?.quick_filter_ids?.length ?? 0
            const tileShortIds = values.insightTiles
                .filter((t): t is DashboardTile & { insight: QueryBasedInsightModel } => !!t.insight)
                .map((t) => t.insight.short_id)

            if (visibleFilterCount > 1) {
                if (tileShortIds.length > 0) {
                    actions.setRefreshStatuses(tileShortIds, false, true)
                }
                await breakpoint(QUICK_FILTER_DEBOUNCE_MS)
            }

            eventUsageLogic.actions.reportDashboardFiltersChanged(values.dashboard, 'quick_filters', {
                visible_filter_count: visibleFilterCount,
            })

            actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Preview,
                forceRefresh: false,
            })
        },
        quickFiltersUrlRestoreComplete: () => {
            if (values.initialQuickFiltersLoaded) {
                return
            }
            actions.setInitialQuickFiltersLoaded(true)

            // If variables are also in the URL and haven't loaded yet, let
            // loadVariablesSuccess trigger the load — by then filtersOverrideForLoad
            // will already include the restored quick filter properties.
            if (SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams && !values.initialVariablesLoaded) {
                return
            }

            // Only trigger the initial load if a prior load hasn't already started it
            if (!values.dashboard && !values.dashboardLoading && !values.dashboardStreaming) {
                if (values.shouldUseStreaming) {
                    actions.loadDashboardStreaming({ action: DashboardLoadAction.InitialLoad })
                } else {
                    actions.loadDashboard({ action: DashboardLoadAction.InitialLoad })
                }
            }
        },
        [variableDataLogic.actionTypes.loadVariablesSuccess]: () => {
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
                allowUndo: false,
            })
        },
        updateDashboardTags: ({ tags }: { tags: string[] }) => {
            actions.triggerDashboardUpdate({ tags })
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
        setDates: ({ date_from, date_to, explicit_date }) => {
            if (!values.canAutoPreview) {
                return
            }

            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                date_from,
                date_to,
                explicitDate: explicit_date ?? values.intermittentFilters.explicitDate,
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
        restoreUrlStateAtEditModeEntry: ({ snapshot }) => {
            try {
                const { currentLocation } = router.values
                const newSearchParams = { ...currentLocation.searchParams }
                delete newSearchParams[SEARCH_PARAM_FILTERS_KEY]
                delete newSearchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY]

                if (snapshot?.filters !== undefined) {
                    newSearchParams[SEARCH_PARAM_FILTERS_KEY] = snapshot.filters
                }
                if (snapshot?.variables !== undefined) {
                    newSearchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY] = snapshot.variables
                }

                return [currentLocation.pathname, newSearchParams, currentLocation.hashParams]
            } catch {
                return undefined
            }
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
            actions.setButtonTileId(null)
            actions.setDashboardMode(null, DashboardEventSource.Browser)
        },

        '/dashboard/:id': () => {
            actions.setSubscriptionMode(false, undefined)
            actions.setTextTileId(null)
            actions.setButtonTileId(null)
            if (values.dashboardMode === DashboardMode.Sharing) {
                actions.setDashboardMode(null, DashboardEventSource.Browser)
            }
        },
        '/dashboard/:id/sharing': () => {
            actions.setSubscriptionMode(false, undefined)
            actions.setTextTileId(null)
            actions.setButtonTileId(null)
            actions.setDashboardMode(DashboardMode.Sharing, DashboardEventSource.Browser)
        },
        '/dashboard/:id/text-tiles/:textTileId': ({ textTileId }) => {
            actions.setSubscriptionMode(false, undefined)
            actions.setDashboardMode(null, DashboardEventSource.Browser)
            actions.setButtonTileId(null)
            actions.setTextTileId(textTileId === undefined ? 'new' : textTileId !== 'new' ? Number(textTileId) : 'new')
        },
        '/dashboard/:id/button-tiles/:buttonTileId': ({ buttonTileId }) => {
            actions.setSubscriptionMode(false, undefined)
            actions.setDashboardMode(null, DashboardEventSource.Browser)
            actions.setTextTileId(null)
            actions.setButtonTileId(
                buttonTileId === undefined ? 'new' : buttonTileId !== 'new' ? Number(buttonTileId) : 'new'
            )
        },
    })),
])

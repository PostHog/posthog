import { deepEqual as equal } from 'fast-equals'
import {
    MakeLogicType,
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
import type { BreakPointFunction } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, beforeUnload, router, urlToAction } from 'kea-router'
import { CombinedLocation } from 'kea-router/lib/utils'
import { subscriptions } from 'kea-subscriptions'
import uniqBy from 'lodash.uniqby'
import posthog from 'posthog-js'
import { ResponsiveLayouts } from 'react-grid-layout'
import type { Layout } from 'react-grid-layout'

import { LemonButton, LemonDialog, lemonToast } from '@posthog/lemon-ui'
import type { DashboardWidgetRunResultApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'
import { isWidgetConfigValidationError, updateDashboardWidgetTile } from '@posthog/products-dashboards/frontend/utils'
import { DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE } from '@posthog/products-dashboards/frontend/widgets/constants'
import {
    applyIssueMetadataToWidgetListResult,
    type WidgetIssueMetadataContext,
    type WidgetIssueMetadataDelta,
} from '@posthog/products-dashboards/frontend/widgets/error_tracking/applyWidgetIssueMetadataChange'

import api, { getJSONOrNull } from 'lib/api'
import { ApiError, isAccessDeniedError } from 'lib/api-error'
import { DataColorTheme } from 'lib/colors'
import { OrganizationMembershipLevel } from 'lib/constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { Dayjs, dayjs, now } from 'lib/dayjs'
import { Link } from 'lib/lemon-ui/Link'
import { apiStatusLogic } from 'lib/logic/apiStatusLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { accessLevelSatisfied } from 'lib/utils/accessControlUtils'
import { deleteInsightWithUndo } from 'lib/utils/deleteWithUndo'
import { clearDOMTextSelection, getJSHeapMemory, uuid } from 'lib/utils/dom'
import {
    DashboardEventSource,
    DashboardFilterChangeType,
    dashboardViewedProperties,
    eventUsageLogic,
    sanitizeDashboard,
    filtersForAnalytics,
    sanitizeQuery,
} from 'lib/utils/eventUsageLogic'
import { objectsEqual } from 'lib/utils/objects'
import { shouldCancelQuery } from 'lib/utils/requests'
import { toParams } from 'lib/utils/url'
import { addInsightToDashboardLogic } from 'scenes/dashboard/addInsightToDashboardModalLogic'
import { BREAKPOINTS, dashboardToSaveableTemplate, getDashboardTileDisplayName } from 'scenes/dashboard/dashboardUtils'
import { liveDashboardIds } from 'scenes/dashboard/liveDashboardIds'
import { calculateDuplicateLayout, calculateLayouts } from 'scenes/dashboard/tileLayouts'
import {
    chunkTileIds,
    fetchRunWidgets,
    findNewlyAddedWidgetTiles,
    isWidgetStale,
    WIDGET_CLIENT_TTL_MS,
} from 'scenes/dashboard/widgetFetchUtils'
import { createDashboardWidgetTileRefreshScheduler } from 'scenes/dashboard/widgetTileRefreshScheduler'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { dataRetentionBannerLogic } from 'scenes/insights/dataRetention/dataRetentionBannerLogic'
import { exceedsRetention } from 'scenes/insights/dataRetention/exceedsRetention'
import { MaxContextInput, createMaxContextHelpers } from 'scenes/max/maxTypes'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { dashboardsModel } from '~/models/dashboardsModel'
import { insightsModel } from '~/models/insightsModel'
import { variableDataLogic } from '~/queries/nodes/DataVisualization/Components/Variables/variableDataLogic'
import { Variable } from '~/queries/nodes/DataVisualization/types'
import {
    BreakdownFilter,
    CompareFilter,
    DashboardFilter,
    DataVisualizationNode,
    HogQLVariable,
    MetricsDashboardVariable,
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
    DashboardTileBasicType,
    DashboardTileIdOrNew,
    DashboardTileSpacing,
    DashboardType,
    DashboardWidgetType,
    InsightColor,
    InsightModel,
    InsightShortId,
    IntervalType,
    ProjectTreeRef,
    TextModel,
    TileLayout,
} from '~/types'

import { DashboardGridCompaction, getDashboardGridCompactor } from 'products/dashboards/frontend/dashboardCustomization'
import {
    dashboardFiltersEqual,
    dashboardVariableValuesEqual,
    getDashboardFilterChanges,
    getDashboardVariableChanges,
    type DashboardSettingsChange,
    type DashboardFilterChange,
} from 'products/dashboards/frontend/dashboardSettings/dashboardChanges'
import {
    type TileGroupChoices,
    dashboardTileGroupChoicesLogic,
} from 'products/dashboards/frontend/dashboardTileGroupChoicesLogic'
import {
    type DashboardSection,
    type SectionLayouts,
    type TileGroupMoveOptions,
    getCollapsedTileGroupKeys,
    getDashboardSections,
    getLayoutAfterSectionChange,
    getLayoutAfterTileMove,
    getSectionLayouts,
    getTileGroupLabel,
    getTileGroupMoveOptions,
} from 'products/dashboards/frontend/dashboardTileSections'

import type { FeatureFlagsSet } from '../../lib/logic/featureFlagLogic'
import type { Node } from '../../queries/schema/schema-general'
import { getResponseBytes, sortDayJsDates } from '../insights/utils'
import { filterVariablesReferencedInQuery } from '../insights/utils/queryUtils'
import { teamLogic } from '../teamLogic'
import {
    BreakdownColorConfig,
    applyAutoBreakdownColors,
    breakdownConfigIdentityMatches,
    buildSharedBreakdownValueLookup,
    extractBreakdownValuesByTile,
    findBreakdownColorConfig,
    hasUnresolvedBreakdownTiles,
    mergeBreakdownColorConfigs,
} from './dashboardBreakdownColors'
import { AUTO_REFRESH_INITIAL_INTERVAL_SECONDS } from './dashboardConstants'
import { DashboardControl, DashboardControlScope, getDashboardControlScopes } from './dashboardControls'
import {
    BREAKPOINT_COLUMN_COUNTS,
    DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES,
    IS_TEST_MODE,
    AUTO_PREVIEW_TILE_LIMIT,
    isEffectiveRefreshStale,
    SEARCH_PARAM_FILTERS_KEY,
    SEARCH_PARAM_QUERY_VARIABLES_KEY,
    combineDashboardFilters,
    combineSavedAndUrlFilters,
    withCompactMetricVariables,
    encodeURLVariables,
    getDashboardWidgetType,
    getEffectiveDateOverride,
    getInsightQueryError,
    getInsightWithRetry,
    isRefreshRejectionStub,
    isWidgetTileVisibleOnPlacement,
    layoutsByTile,
    parseURLFilters,
    parseURLVariables,
    TaskQueue,
    searchParamsWithUrlFilters,
    shouldSharedDashboardAutoForceForStaleTime,
} from './dashboardUtils'
import { TileFiltersOverride } from './TileFiltersOverride'
import { tileLogic } from './tileLogic'

function dashboardSettingsMatch(first: DashboardSettings, second: DashboardSettings): boolean {
    return dashboardFiltersEqual(first.filters, second.filters) && equal(first.variables, second.variables)
}

function reportDashboardTileRefreshed(
    dashboardId: number,
    tile: DashboardTile,
    filters: Record<string, any>,
    variables: Record<string, any>,
    refreshDurationMs: number,
    individualRefresh: boolean,
    filterChange?: PendingFilterChange
): void {
    const insight = tile.insight
    const sanitizedQuery = insight?.query ? sanitizeQuery(insight.query) : {}

    posthog.capture('dashboard insight refreshed', {
        dashboard_id: dashboardId,
        insight_id: insight?.id,
        insight_short_id: insight?.short_id,
        was_cached: tile.is_cached,
        last_refreshed: insight?.last_refresh?.toString(),
        refresh_age: insight?.last_refresh ? now().diff(insight?.last_refresh, 'seconds') : undefined,
        filters: filtersForAnalytics(filters),
        variables,
        refresh_duration_ms: refreshDurationMs,
        individual_refresh: individualRefresh,
        ...sanitizedQuery,
        ...(filterChange
            ? {
                  filter_change_id: filterChange.id,
                  filter_change_duration_ms: Math.floor(performance.now() - filterChange.startTime),
                  all_insights_succeeded: filterChange.remainingInsightIds.size === 0,
              }
            : {}),
    })
}

const TILE_REFRESH_CONCURRENCY = 4

type InsightTileRefreshOutcome = 'refreshed' | 'cached' | 'errored' | 'aborted'

interface InsightTileRefresh {
    actions: Pick<dashboardLogicType['actions'], 'setRefreshStatus' | 'setRefreshError' | 'abortQuery'>
    dashboardId: number
    currentTeamId: number | null
    filters: DashboardFilter
    variables: Record<string, HogQLVariable>
    urlFilters: DashboardFilter
    forceRefresh: boolean
    signal: AbortSignal
    queue: TaskQueue
}

/** One queue for every insight and widget load, so a dashboard never sends more than the cap at the same time. */
function tileLoadQueue(cache: Record<string, any>): TaskQueue {
    return (cache.tileLoadQueue ??= new TaskQueue(TILE_REFRESH_CONCURRENCY))
}

async function refreshInsightTile(
    tile: DashboardTile & { insight: InsightModel },
    {
        actions,
        dashboardId,
        currentTeamId,
        filters,
        variables,
        urlFilters,
        forceRefresh,
        signal,
        queue,
    }: InsightTileRefresh
): Promise<InsightTileRefreshOutcome> {
    const insight = tile.insight
    const queryId = uuid()
    let queryStartTime = performance.now()

    try {
        const refreshedInsight = await queue.run(() => {
            queryStartTime = performance.now()
            actions.setRefreshStatus(insight.short_id, true, true)
            return getInsightWithRetry(
                currentTeamId,
                insight,
                dashboardId,
                queryId,
                forceRefresh ? 'force_blocking' : 'blocking', // 'blocking' returns cached data if available, when manual refresh is triggered we want fresh results
                { signal },
                filters,
                variables,
                tile.filters_overrides
            )
        }, signal)

        const queryError = refreshedInsight ? getInsightQueryError(refreshedInsight) : null
        if (!refreshedInsight || isRefreshRejectionStub(refreshedInsight) || queryError) {
            actions.setRefreshError(insight.short_id, queryError?.code ? queryError : undefined)
            return 'errored'
        }
        dashboardsModel.actions.updateDashboardInsight(refreshedInsight, undefined, dashboardId)
        actions.setRefreshStatus(insight.short_id)
        reportDashboardTileRefreshed(
            dashboardId,
            tile,
            urlFilters,
            variables,
            Math.floor(performance.now() - queryStartTime),
            false
        )
        return refreshedInsight.is_cached ? 'cached' : 'refreshed'
    } catch (e: any) {
        if (shouldCancelQuery(e)) {
            console.warn(`Insight refresh cancelled for ${insight.short_id} due to abort signal:`, e)
            actions.abortQuery({ queryId, queryStartTime, shortId: insight.short_id })
            return 'aborted'
        }
        actions.setRefreshError(insight.short_id, e)
        return 'errored'
    }
}

function abortWidgetLoads(cache: Record<string, any>): void {
    cache.widgetAbortController?.abort()
    cache.widgetAbortController = undefined
}

function abortGroupLoads(cache: Record<string, any>): void {
    cache.groupAbortController?.abort()
    cache.groupAbortController = undefined
}

/** Tiles in closed groups that a refresh skipped, and how that refresh would have loaded them. */
interface WaitingTileRefresh {
    tileIds: number[]
    forceRefresh: boolean
    settings: DashboardSettings
}

/** Tiles in closed groups that a refresh skips wait for their group to open, alongside tiles an earlier refresh skipped. */
function nextWaitingTileRefresh({
    previous,
    tiles,
    collapsedTileIds,
    candidateTileIds,
    forceRefresh,
    settings,
}: {
    previous: WaitingTileRefresh | null
    tiles: DashboardTile[]
    collapsedTileIds: Set<number>
    candidateTileIds: number[]
    forceRefresh: boolean
    settings: DashboardSettings
}): WaitingTileRefresh {
    const groupedTileIds = new Set(tiles.filter((tile) => tile.group_key).map((tile) => tile.id))
    // This refresh aborts a running group load, and a viewer can cancel this refresh too,
    // so a tile keeps waiting until a load of it succeeds.
    const previouslyWaiting = previous?.tileIds.filter((id) => groupedTileIds.has(id)) ?? []
    return {
        tileIds: [...new Set([...previouslyWaiting, ...candidateTileIds.filter((id) => collapsedTileIds.has(id))])],
        // A refresh of only stale tiles must not let a group that a manual refresh skipped show older data.
        forceRefresh: forceRefresh || (previouslyWaiting.length > 0 && !!previous?.forceRefresh),
        settings,
    }
}

/** Open groups that still hold tiles an earlier refresh skipped. */
function openTileGroupsWaiting(
    tiles: DashboardTile[],
    collapsedTileIds: Set<number>,
    waiting: WaitingTileRefresh | null
): Set<string> {
    return new Set(
        tiles
            .filter((tile) => tile.group_key && !collapsedTileIds.has(tile.id) && waiting?.tileIds.includes(tile.id))
            .map((tile) => tile.group_key as string)
    )
}

export interface DashboardLogicProps {
    id: number
    dashboard?: DashboardType
    placement?: DashboardPlacement
    /** Hides the tile menus and the drag-to-edit controls, even for users who can edit the dashboard. */
    readOnly?: boolean
}

interface RevealedTileGroup {
    insightId: string
    groupKey: string | null
}

interface PendingFilterChange {
    id: string
    startTime: number
    settings: DashboardSettings
    remainingInsightIds: Set<InsightShortId>
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
    w: number | null
}

export interface DashboardSettings {
    filters: DashboardFilter
    variables: Record<string, HogQLVariable>
}

export type DashboardSettingsState = 'unsavedChanges' | 'saved'

export interface DashboardEditing {
    filters: boolean
    layout: boolean
}

type DashboardEditSaveScope = 'colors' | 'layout'

function parseDashboardTileId(tileId: string | undefined): DashboardTileIdOrNew {
    const parsedTileId = Number(tileId)
    return Number.isNaN(parsedTileId) ? null : parsedTileId
}

// pinned: `method` property values of the "dashboard tile moved between groups" event
export type TileGroupMoveMethod = 'menu' | 'drag'

/** Where a tile sits. Its layout and its group save together, so one never goes back without the other. */
export interface TilePlacement {
    layouts: DashboardTile['layouts']
    group_key: string | null
}

const NO_SAVED_PLACEMENT: TilePlacement = { layouts: undefined, group_key: null }

const savedTilePlacement = (placements: Record<number, TilePlacement>, tileId: number): TilePlacement =>
    placements[tileId] ?? NO_SAVED_PLACEMENT

const tilePlacement = (tile: DashboardTile): TilePlacement => ({
    layouts: tile.layouts,
    group_key: tile.group_key ?? null,
})

type GridCell = Pick<Layout[number], 'x' | 'y' | 'w' | 'h'>

const sameGridCell = (a: GridCell, b: GridCell): boolean => a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h

const withStagedCellReverted = (
    layout: Layout,
    tileId: number,
    moved: GridCell,
    saved: GridCell | undefined
): Layout => {
    const staged = layout.find((item) => item.i === String(tileId))
    if (!staged || !sameGridCell(staged, moved)) {
        return layout
    }
    return saved
        ? layout.map((item) => (item === staged ? { ...item, x: saved.x, y: saved.y, w: saved.w, h: saved.h } : item))
        : layout.filter((item) => item !== staged)
}

const tilePlacementsFromDashboard = (dashboard: DashboardType | null | undefined): Record<number, TilePlacement> =>
    Object.fromEntries((dashboard?.tiles ?? []).map((tile) => [tile.id, tilePlacement(tile)]))

const tileGroupChanged = (tile: DashboardTile, saved: TilePlacement | undefined): boolean =>
    (tile.group_key ?? null) !== (saved?.group_key ?? null)

const withTilePlacement = (tile: DashboardTile, placement: TilePlacement | undefined): DashboardTile => ({
    ...tile,
    layouts: placement?.layouts,
    group_key: placement?.group_key ?? null,
})

const withSavedTilePlacements = (
    dashboard: DashboardType,
    savedPlacements: Record<number, TilePlacement>
): DashboardType => ({
    ...dashboard,
    tiles: dashboard.tiles.map((tile) => withTilePlacement(tile, savedPlacements[tile.id])),
})

/**
 * Runs layout saves one after another. The server then applies them in the order they were made, and each one
 * starts from the dashboard that the save before it left, so a save response cannot undo a later move.
 * A loader writes its result after `save` returns, so it passes `applied` to hold the next save until then.
 */
interface TileSaveQueueOwner {
    cache: Record<string, any>
    mount: () => () => void
}

function enqueueTileSave<T>(
    { cache, mount }: TileSaveQueueOwner,
    save: () => Promise<T>,
    applied: Promise<void> = Promise.resolve()
): Promise<T> {
    const previous = cache.tileSaves as Promise<unknown> | undefined
    // A queued save reads the store when it starts, so the logic stays mounted until the queue is empty.
    if (!previous) {
        cache.releaseTileSaveMount = mount()
    }
    // With nothing queued the save starts at once, so its request goes out in the same tick as the action.
    const result = previous ? previous.then(save) : save()
    const queued = result.then(
        () => applied,
        () => undefined
    )
    cache.tileSaves = queued
    void queued.then(() => {
        if (cache.tileSaves === queued) {
            cache.tileSaves = undefined
            cache.releaseTileSaveMount()
        }
    })
    return result
}

function enqueueEditSave<T>(owner: TileSaveQueueOwner, save: () => Promise<T>): Promise<T> {
    let markApplied = (): void => {}
    const applied = new Promise<void>((resolve) => {
        markApplied = resolve
    })
    const start = (): Promise<T> => {
        owner.cache.resolveEditSaveApplied = markApplied
        return save()
    }
    return enqueueTileSave(owner, start, applied)
}

const groupKeyUpdate = (tile: DashboardTile, saved: TilePlacement | undefined): { group_key?: string | null } =>
    tileGroupChanged(tile, saved) ? { group_key: tile.group_key ?? null } : {}

function calculateDraftLayouts(
    tiles: DashboardTile[],
    draftLayouts: ResponsiveLayouts | null,
    savedPlacements?: Record<DashboardTile['id'], TilePlacement>
): ResponsiveLayouts {
    if (!draftLayouts) {
        return calculateLayouts(tiles)
    }

    const draftSmByTile = new Map(draftLayouts.sm?.map((layout) => [layout.i, layout]))
    const tilesWithDraft = tiles.map((tile) => {
        const savedSm = savedPlacements?.[tile.id]?.layouts?.sm
        const serverSm = tile.layouts?.sm
        const serverChangedSm = savedSm && serverSm && !equal(savedSm, serverSm)
        const sm = serverChangedSm ? serverSm : (draftSmByTile.get(String(tile.id)) ?? serverSm)

        return sm ? ({ ...tile, layouts: { ...tile.layouts, sm } } as DashboardTile) : tile
    })

    return calculateLayouts(tilesWithDraft)
}

function mergeUpdatedWidgetTileIntoDashboard(dashboard: DashboardType, updatedTile: DashboardTile): DashboardType {
    return {
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
    } as DashboardType
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardLogicValues {
    internetConnectionIssue: boolean // apiStatusLogic
    tileGroupChoices: TileGroupChoices // dashboardTileGroupChoicesLogic
    retentionMonths: number | null // dataRetentionBannerLogic
    retentionPeriodLabel: string | null // dataRetentionBannerLogic
    warningEligible: boolean // dataRetentionBannerLogic
    getTheme: (themeId: number | string | null | undefined) => DataColorTheme | null // dataThemeLogic
    featureFlags: FeatureFlagsSet // featureFlagLogic
    currentTeamId: number | null // teamLogic
    variables: Variable[] // variableDataLogic
    accessDeniedToDashboard: boolean
    addWidgetCollapsedGroups: string[]
    addWidgetFilteredGroups: string[]
    addWidgetModalOpen: boolean
    addWidgetSelectedTypes: string[]
    addWidgetTileLoading: boolean
    anyInsightExceedsRetention: boolean
    apiUrl: (
        refresh?: RefreshType | undefined,
        filtersOverride?: DashboardFilter | undefined,
        variablesOverride?: Record<string, HogQLVariable> | undefined,
        layoutSize?: 'sm' | 'xs' | undefined
    ) => string
    asDashboardTemplate: DashboardTemplateEditorType | undefined
    autoBreakdownColorsEnabled: boolean
    autoRefresh: {
        enabled: boolean
        interval: number
    }
    blockRefresh: boolean
    breadcrumbs: Breadcrumb[]
    breakdownValuesIncomplete: boolean
    buttonTileId: DashboardTileIdOrNew
    canAutoPreview: boolean
    canEditDashboard: boolean
    canRestrictDashboard: boolean
    canSaveProjectDashboardTemplate: boolean
    cancellingPreview: boolean
    changedFilterCount: number
    collapsedTileGroupKeys: string[]
    collapsedTileIds: Set<number>
    columns: number | null
    containerWidth: number | null
    currentDashboardSettings: DashboardSettings
    currentDashboardVariables: Record<string, HogQLVariable>
    currentLayoutSize: 'sm' | 'xs'
    dashboard: DashboardType | null
    dashboardControlScopes: Record<DashboardControl, DashboardControlScope>
    dashboardCustomizeMenuOpen: boolean
    dashboardEditing: DashboardEditing | null
    dashboardFailedToLoad: boolean
    dashboardFiltersSaving: boolean
    dashboardLoadData: {
        action: DashboardLoadAction | undefined
        dashboardQueryId: string
        responseBytes: number
        startTime: number
    }
    dashboardLoading: boolean
    dashboardMode: DashboardMode | null
    dashboardSettingsChanges: DashboardSettingsChange[]
    dashboardSettingsDraft: DashboardSettings | null
    dashboardSettingsState: DashboardSettingsState
    dashboardStreaming: boolean
    dashboardTileSpacingSaving: boolean
    dataColorTheme: DataColorTheme | null
    dataColorThemeId: number | null
    draftLayouts: ResponsiveLayouts | null
    effectiveBreakdownColors: BreakdownColorConfig[]
    effectiveEditBarFilters: DashboardFilter
    effectiveLastRefresh: Dayjs | null
    effectiveRefreshFilters: DashboardFilter
    effectiveVariablesAndAssociatedInsights: {
        insightNames: string[]
        variable: Variable
    }[]
    error404: boolean
    externalFilters: DashboardFilter
    filterChanges: DashboardFilterChange[]
    filterEditModeActive: boolean
    filtersDirty: boolean
    filtersOverrideForLoad: DashboardFilter
    filtersOverrideForRequests: DashboardFilter
    hasInvalidDashboardId: boolean
    hasUnsavedColorChanges: boolean
    hasUnsavedLayoutChanges: boolean
    hasVariables: boolean
    highlightedInsightId: any
    initialDashboardSettingsOverride: DashboardSettings
    initialVariablesLoaded: boolean
    insightTiles: DashboardTile[]
    isPinned: boolean
    isRefreshing: (id: string) => boolean
    isRefreshingQueued: (id: string) => boolean
    isSavingTags: boolean
    itemsLoading: boolean
    lastDashboardRefresh: Dayjs | null
    layout: Layout | undefined
    layoutEditMode: boolean
    layoutForItem: Record<string, TileLayout>
    layoutZoom: number
    layouts: ResponsiveLayouts
    loadLayoutFromServerOnPreview: boolean
    loadTimer: Date | null
    loadingPreview: boolean
    maxContext: MaxContextInput[]
    nextAllowedDashboardRefresh: Dayjs | null
    nextWidgetStaleAt: number | null
    oldestRefreshed: Dayjs | null
    pageVisibility: boolean
    pendingInsertion: PendingInsertion | null
    persistableDashboardFilters: DashboardFilter
    placement: DashboardPlacement
    previewedDashboardSettings: DashboardSettings | null
    projectTreeRef: ProjectTreeRef
    readOnly: boolean
    refreshEligibilityTick: number
    refreshMetrics: {
        completed: number
        total: number
    }
    refreshStatus: Record<string, RefreshStatus>
    refreshTilesTotal: number | null
    revealedTileGroup: RevealedTileGroup | null
    savedDashboardSettings: DashboardSettings
    savedTilePlacements: Record<DashboardTile['id'], TilePlacement>
    scrollToBottomSignal: number
    settingsForRefresh: DashboardSettings
    shouldReportOnAPILoad: boolean
    shouldUseStreaming: boolean
    showApplyFiltersBanner: boolean
    showButtonTileModal: boolean
    showImageTileModal: boolean
    showRetentionBanner: boolean
    showSubscriptions: boolean
    showTextTileModal: boolean
    sidePanelContext: SidePanelSceneContext | null
    sizeKey: DashboardLayoutSize | undefined
    sortedDates: Dayjs[]
    subscriptionId: number | 'new' | null
    temporaryBreakdownColors: BreakdownColorConfig[]
    temporaryDataColorThemeId: {
        themeId: number | null
    } | null
    terraformModalOpen: boolean
    textTileId: DashboardTileIdOrNew
    textTiles: DashboardTile[]
    tileGroupMoveOptions: Record<number, TileGroupMoveOptions>
    tileGroupSectionLayouts: SectionLayouts[]
    tileGroupSections: DashboardSection[]
    tileGroupSectionsEnabled: boolean
    tiles: DashboardTile[]
    urlFilters: DashboardFilter
    urlSearchParamsAtEditModeEntry: {
        filters?: unknown
        variables?: unknown
    } | null
    urlVariables: Record<string, HogQLVariable>
    variablesDirty: boolean
    waitingTileRefresh: WaitingTileRefresh | null
    widgetRefreshStatus: Record<
        number,
        {
            error?: string | null
            fetchedAt?: number
            loading?: boolean
        }
    >
    widgetResultsByTileId: Record<number, DashboardWidgetRunResultApi>
    widgetTileUpdate: null
    widgetTileUpdateLoading: boolean
    widgetTiles: DashboardTile[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardLogicActions {
    abortAnyRunningQuery: () => {
        value: true
    }
    abortQuery: (payload: { queryId: string; queryStartTime: number; shortId: InsightShortId }) => {
        queryId: string
        queryStartTime: number
        shortId: InsightShortId
    }
    addWidgetTileFinished: () => {
        value: true
    }
    addWidgetTiles: (payload: {
        dashboardId: number
        widgets: {
            config: Record<string, unknown>
            widgetType: string
        }[]
    }) => {
        dashboardId: number
        widgets: {
            config: Record<string, unknown>
            widgetType: string
        }[]
    }
    applyDashboardUpdate: (
        dashboard: DashboardType,
        savedPlacements: Record<number, TilePlacement>
    ) => {
        dashboard: DashboardType
        savedPlacements: Record<number, TilePlacement>
    }
    applyWidgetIssueMetadataChange: (payload: {
        context: WidgetIssueMetadataContext
        delta: WidgetIssueMetadataDelta
        issueId: string
        tileId: number
    }) => {
        context: WidgetIssueMetadataContext
        delta: WidgetIssueMetadataDelta
        issueId: string
        tileId: number
    }
    cancelDashboardRefresh: () => {
        value: true
    }
    cancelLayoutEdit: () => {
        value: true
    }
    changeDashboardGridCompaction: (layoutCompaction: DashboardGridCompaction) => {
        layoutCompaction: DashboardGridCompaction
    }
    changeDashboardTileSpacing: (tileSpacing: DashboardTileSpacing) => {
        tileSpacing: DashboardTileSpacing
    }
    clearAddWidgetSelectedTypes: () => {
        value: true
    }
    clearDashboardSettingsUrlOverrides: () => {
        value: true
    }
    clearDraftLayouts: () => boolean
    clearInitialDashboardSettingsOverride: () => {
        value: true
    }
    clearWaitingTileRefresh: (tileIds: number[]) => {
        tileIds: number[]
    }
    closeTileModal: () => {
        value: true
    }
    copyToDashboard: (
        tile: DashboardTile,
        fromDashboard: number,
        toDashboard: number,
        toDashboardName: string
    ) => {
        fromDashboard: number
        tile: DashboardTile
        toDashboard: number
        toDashboardName: string
    }
    copyToDashboardFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    copyToDashboardSuccess: (
        dashboard: DashboardType | null,
        payload?: {
            fromDashboard: number
            tile: DashboardTile
            toDashboard: number
            toDashboardName: string
        }
    ) => {
        dashboard: DashboardType | null
        payload?: {
            fromDashboard: number
            tile: DashboardTile
            toDashboard: number
            toDashboardName: string
        }
    }
    dashboardNotFound: () => {
        value: true
    }
    discardDashboardChanges: () => {
        value: true
    }
    discardLayoutChanges: () => {
        value: true
    }
    duplicateTile: (tile: DashboardTile) => {
        tile: DashboardTile
    }
    duplicateTileFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    duplicateTileSuccess: (
        dashboard: DashboardType,
        payload?: {
            tile: DashboardTile
        }
    ) => {
        dashboard: DashboardType
        payload?: {
            tile: DashboardTile
        }
    }
    forceRefreshIfStale: () => {
        value: true
    }
    loadDashboard: (payload: { action: DashboardLoadAction }) => {
        action: DashboardLoadAction
    }
    loadDashboardFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDashboardMetadataSuccess: (dashboard: DashboardType | null) => {
        dashboard: DashboardType | null
    }
    loadDashboardStreaming: (payload: {
        action: DashboardLoadAction
        manualDashboardRefresh?: boolean
        retry?: boolean
    }) => {
        action: DashboardLoadAction
        manualDashboardRefresh?: boolean | undefined
        retry?: boolean | undefined
    }
    loadDashboardStreamingFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadDashboardStreamingSuccess: (
        dashboard: DashboardType | null,
        payload?: {
            action: DashboardLoadAction
            manualDashboardRefresh?: boolean | undefined
            retry?: boolean | undefined
        }
    ) => {
        dashboard: DashboardType | null
        payload?: {
            action: DashboardLoadAction
            manualDashboardRefresh?: boolean | undefined
            retry?: boolean | undefined
        }
    }
    loadDashboardSuccess: (
        dashboard: DashboardType | null,
        payload?: {
            action: DashboardLoadAction
        }
    ) => {
        dashboard: DashboardType | null
        payload?: {
            action: DashboardLoadAction
        }
    }
    loadingDashboardItemsStarted: (action: DashboardLoadAction) => {
        action: DashboardLoadAction
    }
    moveTileToSection: (
        tileId: number,
        sectionKey: string | null,
        cell: {
            x: number
            y: number
        } | null,
        method: TileGroupMoveMethod
    ) => {
        cell: {
            x: number
            y: number
        } | null
        method: TileGroupMoveMethod
        sectionKey: string | null
        tileId: number
    }
    moveToDashboard: (
        tile: DashboardTile,
        fromDashboard: number,
        toDashboard: number,
        toDashboardName: string,
        allowUndo?: boolean
    ) => {
        allowUndo: boolean
        fromDashboard: number
        tile: DashboardTile
        toDashboard: number
        toDashboardName: string
    }
    moveToDashboardFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    moveToDashboardSuccess: (
        dashboard: DashboardType | null,
        payload?: {
            allowUndo: boolean
            fromDashboard: number
            tile: DashboardTile
            toDashboard: number
            toDashboardName: string
        }
    ) => {
        dashboard: DashboardType | null
        payload?: {
            allowUndo: boolean
            fromDashboard: number
            tile: DashboardTile
            toDashboard: number
            toDashboardName: string
        }
    }
    openAddInsightModal: () => {
        value: true
    }
    openButtonTileModal: () => {
        value: true
    }
    openImageTileModal: () => {
        value: true
    }
    openTextTileModal: () => {
        value: true
    }
    overrideVariableValue: (
        variableId: string,
        value: any,
        isNull: boolean
    ) => {
        isNull: boolean
        value: any
        variableId: string
    }
    previewDashboardChanges: () => {
        value: true
    }
    previewDashboardChangesFailure: () => {
        value: true
    }
    receiveTileFromStream: (data: { order: number; tile: any }) => {
        order: number
        tile: any
    }
    recheckRefreshEligibility: () => {
        value: true
    }
    refreshDashboardItem: (payload: { tile: DashboardTile }) => {
        tile: DashboardTile
    }
    refreshDashboardItems: (payload: {
        action: DashboardLoadAction | RefreshDashboardItemsAction
        forceRefresh?: boolean
        previewUnsavedFilters?: boolean
    }) => {
        action: DashboardLoadAction | RefreshDashboardItemsAction
        forceRefresh?: boolean | undefined
        previewUnsavedFilters?: boolean | undefined
    }
    refreshDashboardWidgets: (payload: { forceRefresh?: boolean; tileIds: number[] }) => {
        forceRefresh?: boolean | undefined
        tileIds: number[]
    }
    refreshTileGroup: (groupKey: string) => {
        groupKey: string
    }
    removeTile: (tile: DashboardTile) => {
        tile: DashboardTile
    }
    removeTileFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    removeTileSuccess: (
        dashboard: DashboardType | null,
        payload?: {
            tile: DashboardTile
        }
    ) => {
        dashboard: DashboardType | null
        payload?: {
            tile: DashboardTile
        }
    }
    reportDashboardFilterChange: (
        changeType: DashboardFilterChangeType,
        properties: Record<string, boolean | number | string | null | undefined>
    ) => {
        changeType: DashboardFilterChangeType
        properties: Record<string, boolean | number | string | null | undefined>
    }
    reportDashboardViewed: () => {
        value: true
    }
    reportDashboardViewedEvent: (
        dashboard: DashboardType,
        lastRefreshed: Dayjs | null,
        delay?: number
    ) => {
        dashboard: DashboardType
        delay: number | undefined
        lastRefreshed: Dayjs | null
    }
    reportInsightsViewed: (insights: InsightModel[]) => {
        insights: InsightModel<Node<Record<string, any>>>[]
    }
    requestScrollToBottom: () => {
        value: true
    }
    resetInterval: () => {
        value: true
    }
    resetUrlFilters: () => boolean
    resetUrlVariables: () => {
        value: true
    }
    restoreTemporaryColorState: (
        colors: BreakdownColorConfig[],
        themeId: {
            themeId: number | null
        } | null
    ) => {
        colors: BreakdownColorConfig[]
        themeId: {
            themeId: number | null
        } | null
    }
    retryDashboardLoad: () => {
        value: true
    }
    revealHighlightedInsight: () => {
        value: true
    }
    saveDashboardChanges: () => {
        value: true
    }
    saveDashboardChangesFailure: (error: string) => {
        error: string
    }
    saveDashboardChangesSuccess: (
        dashboard: DashboardType | null,
        settings: DashboardSettings | null
    ) => {
        dashboard: DashboardType | null
        settings: DashboardSettings | null
    }
    saveDashboardColorChanges: () => {
        value: true
    }
    saveDashboardGridCompaction: (layoutCompaction: DashboardGridCompaction) => {
        layoutCompaction: DashboardGridCompaction
    }
    saveDashboardTileSpacing: (tileSpacing: DashboardTileSpacing) => {
        tileSpacing: DashboardTileSpacing
    }
    saveEditModeChanges: (scope: DashboardEditSaveScope) => {
        scope: DashboardEditSaveScope
    }
    saveEditModeChangesFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    saveEditModeChangesSuccess: (
        dashboard: DashboardType | null,
        payload?: {
            scope: DashboardEditSaveScope
        }
    ) => {
        dashboard: DashboardType | null
        payload?: {
            scope: DashboardEditSaveScope
        }
    }
    saveLayout: () => {
        value: true
    }
    saveLayoutChanges: () => {
        value: true
    }
    scheduleRefreshDashboardWidgets: (tileId: number) => {
        tileId: number
    }
    setAccessDeniedToDashboard: () => {
        value: true
    }
    setAddWidgetModalOpen: (open: boolean) => {
        open: boolean
    }
    setAutoRefresh: (
        enabled: boolean,
        interval: number
    ) => {
        enabled: boolean
        interval: number
    }
    setBreakdownColorConfig: (config: BreakdownColorConfig) => {
        config: BreakdownColorConfig
    }
    setBreakdownFilter: (breakdown_filter: BreakdownFilter | null) => {
        breakdown_filter: BreakdownFilter | null
    }
    setButtonTileId: (buttonTileId: DashboardTileIdOrNew) => {
        buttonTileId: DashboardTileIdOrNew
    }
    setCompareFilter: (compareFilter: CompareFilter | null) => {
        compareFilter: CompareFilter | null
    }
    setDashboardCustomizeMenuOpen: (open: boolean) => {
        open: boolean
    }
    setDashboardEditing: (
        editing: DashboardEditing | null,
        source: DashboardEventSource
    ) => {
        editing: DashboardEditing | null
        source: DashboardEventSource
    }
    setDashboardGridCompaction: (layoutCompaction: DashboardGridCompaction) => {
        layoutCompaction: DashboardGridCompaction
    }
    setDashboardMode: (
        mode: DashboardMode | null,
        source: DashboardEventSource
    ) => {
        mode: DashboardMode | null
        source: DashboardEventSource
    }
    setDashboardSettingsDraft: (settings: DashboardSettings | null) => {
        settings: DashboardSettings | null
    }
    setDashboardStreamFailed: () => {
        value: true
    }
    setDashboardTileSpacing: (tileSpacing: DashboardTileSpacing) => {
        tileSpacing: DashboardTileSpacing
    }
    setDashboardTileSpacingSaving: (saving: boolean) => {
        saving: boolean
    }
    setDataColorThemeId: (dataColorThemeId: number | null) => {
        dataColorThemeId: number | null
    }
    setDates: (
        dateFrom: string | null,
        dateTo: string | null | undefined,
        explicitDate?: boolean
    ) => {
        dateFrom: string | null
        dateTo: string | null | undefined
        explicitDate: boolean | undefined
    }
    setExternalFilters: (filters: DashboardFilter) => {
        filters: DashboardFilter
    }
    setFilterTestAccounts: (filterTestAccounts: boolean | null) => {
        filterTestAccounts: boolean | null
    }
    setInitialDashboardSettingsOverride: (settings: DashboardSettings) => {
        settings: DashboardSettings
    }
    setInitialLoadResponseBytes: (responseBytes: number) => {
        responseBytes: number
    }
    setInitialVariablesLoaded: (initialVariablesLoaded: boolean) => {
        initialVariablesLoaded: boolean
    }
    setInterval: (interval: IntervalType | null) => {
        interval: IntervalType | null
    }
    setLayoutZoom: (layoutZoom: number) => {
        layoutZoom: number
    }
    setLoadLayoutFromServerOnPreview: (loadLayoutFromServerOnPreview: boolean) => {
        loadLayoutFromServerOnPreview: boolean
    }
    setMetricVariables: (metricVariables: MetricsDashboardVariable[] | null) => {
        metricVariables: MetricsDashboardVariable[] | null
    }
    setPageVisibility: (visible: boolean) => {
        visible: boolean
    }
    setPreviewedDashboardSettings: (settings: DashboardSettings | null) => {
        settings: DashboardSettings | null
    }
    setProperties: (properties: AnyPropertyFilter[] | null) => {
        properties: AnyPropertyFilter[] | null
    }
    setRefreshError: (
        shortId: InsightShortId,
        error?: Error
    ) => {
        error: Error | undefined
        shortId: InsightShortId
    }
    setRefreshStatus: (
        shortId: InsightShortId,
        loading?: any,
        queued?: any
    ) => {
        loading: any
        queued: any
        shortId: InsightShortId
    }
    setRefreshStatuses: (
        shortIds: InsightShortId[],
        loading?: any,
        queued?: any
    ) => {
        loading: any
        queued: any
        shortIds: InsightShortId[]
    }
    setRefreshTilesTotal: (total: number) => {
        total: number
    }
    setRevealedTileGroup: (revealedTileGroup: RevealedTileGroup | null) => {
        revealedTileGroup: RevealedTileGroup | null
    }
    setShouldReportOnAPILoad: (shouldReport: boolean) => {
        shouldReport: boolean
    }
    setSubscriptionMode: (
        enabled: boolean,
        id?: number | 'new'
    ) => {
        enabled: boolean
        id: number | 'new' | undefined
    }
    setTerraformModalOpen: (open: boolean) => {
        open: boolean
    }
    setTextTileId: (textTileId: DashboardTileIdOrNew) => {
        textTileId: DashboardTileIdOrNew
    }
    setTileOverride: (tile: DashboardTile) => {
        tile: DashboardTile
    }
    setTileProperty: (
        tileId: number,
        properties: Partial<Pick<DashboardTile, 'color' | 'group_key' | 'layouts' | 'show_description'>>
    ) => {
        properties: Partial<Pick<DashboardTile, 'color' | 'group_key' | 'layouts' | 'show_description'>>
        tileId: number
    }
    setWaitingTileRefresh: (waiting: WaitingTileRefresh) => {
        waiting: WaitingTileRefresh
    }
    setWidgetRefreshStatuses: (
        tileIds: number[],
        loading: boolean,
        error?: string | null
    ) => {
        error: string | null | undefined
        loading: boolean
        tileIds: number[]
    }
    setWidgetRunResults: (results: Record<number, DashboardWidgetRunResultApi>) => {
        results: Record<number, DashboardWidgetRunResultApi>
    }
    stageLayouts: (layouts: ResponsiveLayouts) => {
        layouts: Partial<Record<string, Layout>>
    }
    stopWidgetRefreshes: (tileIds: number[]) => {
        tileIds: number[]
    }
    tilePlacementsSaved: (placements: Record<number, TilePlacement>) => {
        placements: Record<number, TilePlacement>
    }
    tileStreamingComplete: () => {
        value: true
    }
    tileStreamingFailure: (
        error: any,
        willRetry?: boolean
    ) => {
        error: any
        willRetry: boolean
    }
    toggleAddWidgetCollapsedGroup: (groupId: string) => {
        groupId: string
    }
    toggleAddWidgetFilteredGroup: (groupId: string) => {
        groupId: string
    }
    toggleAddWidgetSelectedType: (widgetType: string) => {
        widgetType: string
    }
    togglePinned: () => {
        value: true
    }
    toggleTileDescription: (tileId: number) => {
        tileId: number
    }
    toggleTileGroup: (groupKey: string) => {
        groupKey: string
    }
    triggerDashboardRefresh: () => {
        value: true
    }
    triggerDashboardUpdate: (payload: any) => {
        payload: any
    }
    updateContainerWidth: (
        containerWidth: number,
        columns: number
    ) => {
        columns: number
        containerWidth: number
    }
    updateDashboardLastRefresh: (lastDashboardRefresh: Dayjs) => {
        lastDashboardRefresh: Dayjs
    }
    updateDashboardTags: (tags: string[]) => {
        tags: string[]
    }
    updateLayouts: (layouts: ResponsiveLayouts) => {
        layouts: Partial<Record<string, Layout>>
    }
    updateTileColor: (
        tileId: number,
        color: InsightColor | null
    ) => {
        color: InsightColor | null
        tileId: number
    }
    updateTileGroupSectionLayout: (layouts: ResponsiveLayouts) => {
        layouts: Partial<Record<string, Layout>>
    }
    updateWidgetTile: ({
        tile,
        config,
        name,
        description,
    }: {
        config?: Record<string, unknown>
        description?: string
        name?: string | null
        tile: DashboardTile
    }) => {
        tile: DashboardTile
        config?: Record<string, unknown>
        name?: string | null
        description?: string
    }
    updateWidgetTileFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    updateWidgetTileSuccess: (
        widgetTileUpdate: null,
        payload?: {
            tile: DashboardTile
            config?: Record<string, unknown>
            name?: string | null
            description?: string
        }
    ) => {
        widgetTileUpdate: null
        payload?: {
            tile: DashboardTile
            config?: Record<string, unknown>
            name?: string | null
            description?: string
        }
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardLogicMeta {
    key: number | 'invalid'
    sharedListeners: {
        reportRefreshTiming: (
            payload: any,
            breakpoint: BreakPointFunction,
            action: {
                type: string
                payload: any
            },
            previousState: any
        ) => void | Promise<void>
        reportLoadTiming: (
            payload: any,
            breakpoint: BreakPointFunction,
            action: {
                type: string
                payload: any
            },
            previousState: any
        ) => void | Promise<void>
        handleDashboardLoadComplete: (
            payload: any,
            breakpoint: BreakPointFunction,
            action: {
                type: string
                payload: any
            },
            previousState: any
        ) => void | Promise<void>
    }
    __keaTypeGenInternalSelectorTypes: {
        filterEditModeActive: (dashboardEditing: DashboardEditing | null) => boolean
        layoutEditMode: (dashboardEditing: DashboardEditing | null) => boolean
        shouldUseStreaming: (featureFlags: FeatureFlagsSet) => boolean
        canAutoPreview: (insightTiles: DashboardTile[]) => boolean
        savedDashboardSettings: (dashboard: DashboardType | null) => DashboardSettings
        currentDashboardSettings: (
            savedDashboardSettings: DashboardSettings,
            initialDashboardSettingsOverride: DashboardSettings,
            dashboardSettingsDraft: DashboardSettings | null
        ) => DashboardSettings
        settingsForRefresh: (
            savedDashboardSettings: DashboardSettings,
            initialDashboardSettingsOverride: DashboardSettings,
            previewedDashboardSettings: DashboardSettings | null
        ) => DashboardSettings
        dashboardSettingsState: (
            savedDashboardSettings: DashboardSettings,
            currentDashboardSettings: DashboardSettings,
            variables: Variable[]
        ) => DashboardSettingsState
        showApplyFiltersBanner: (canAutoPreview: boolean, dashboardSettingsState: DashboardSettingsState) => boolean
        urlFilters: (searchParams: Record<string, any>) => DashboardFilter
        filtersOverrideForLoad: (
            externalFilters: DashboardFilter,
            currentDashboardSettings: DashboardSettings
        ) => DashboardFilter
        filtersOverrideForRequests: (
            filtersOverrideForLoad: DashboardFilter,
            savedDashboardSettings: DashboardSettings
        ) => DashboardFilter
        effectiveEditBarFilters: (
            externalFilters: DashboardFilter,
            currentDashboardSettings: DashboardSettings
        ) => DashboardFilter
        persistableDashboardFilters: (currentDashboardSettings: DashboardSettings) => DashboardFilter
        filtersDirty: (
            dashboardSettingsState: DashboardSettingsState,
            dashboard: DashboardType | null,
            persistableDashboardFilters: DashboardFilter
        ) => boolean
        variablesDirty: (
            dashboardSettingsState: DashboardSettingsState,
            dashboard: DashboardType | null,
            currentDashboardVariables: Record<string, HogQLVariable>
        ) => boolean
        filterChanges: (
            dashboard: DashboardType | null,
            persistableDashboardFilters: DashboardFilter
        ) => DashboardFilterChange[]
        changedFilterCount: (filterChanges: DashboardSettingsChange[]) => number
        dashboardSettingsChanges: (
            savedDashboardSettings: DashboardSettings,
            currentDashboardSettings: DashboardSettings,
            variables: Variable[]
        ) => DashboardSettingsChange[]
        anyInsightExceedsRetention: (
            insightTiles: DashboardTile[],
            effectiveEditBarFilters: DashboardFilter,
            retentionMonths: number | null
        ) => boolean
        showRetentionBanner: (
            warningEligible: boolean,
            anyInsightExceedsRetention: boolean,
            placement: DashboardPlacement
        ) => boolean
        effectiveRefreshFilters: (
            externalFilters: DashboardFilter,
            settingsForRefresh: DashboardSettings
        ) => DashboardFilter
        currentDashboardVariables: (currentDashboardSettings: DashboardSettings) => Record<string, HogQLVariable>
        hasUnsavedLayoutChanges: (
            dashboard: DashboardType | null,
            savedTilePlacements: Record<number, TilePlacement>,
            draftLayouts: Partial<Record<string, Layout>> | null
        ) => boolean
        effectiveVariablesAndAssociatedInsights: (
            dashboard: DashboardType | null,
            variables: Variable[],
            currentDashboardVariables: Record<string, HogQLVariable>
        ) => {
            insightNames: string[]
            variable: Variable
        }[]
        urlVariables: (
            searchParams: Record<string, any>,
            variables: Variable[],
            initialVariablesLoaded: boolean
        ) => Record<string, HogQLVariable>
        hasVariables: (
            effectiveVariablesAndAssociatedInsights: {
                insightNames: string[]
                variable: Variable
            }[]
        ) => boolean
        asDashboardTemplate: (dashboard: DashboardType | null) => DashboardTemplateEditorType | undefined
        placement: (arg: any) => DashboardPlacement
        readOnly: (arg: any) => boolean
        apiUrl: (
            id: number
        ) => (
            refresh?: RefreshType | undefined,
            filtersOverride?: DashboardFilter | undefined,
            variablesOverride?: Record<string, HogQLVariable> | undefined,
            layoutSize?: 'sm' | 'xs' | undefined
        ) => string
        currentLayoutSize: (containerWidth: number | null) => 'sm' | 'xs'
        tiles: (dashboard: DashboardType | null) => DashboardTile[]
        widgetTiles: (tiles: DashboardTile[]) => DashboardTile[]
        tileGroupSectionsEnabled: (featureFlags: FeatureFlagsSet) => boolean
        collapsedTileGroupKeys: (
            tileGroupSectionsEnabled: boolean,
            placement: DashboardPlacement,
            tiles: DashboardTile[],
            dashboard: DashboardType | null,
            tileGroupChoices: TileGroupChoices,
            revealedTileGroup: RevealedTileGroup | null
        ) => string[]
        collapsedTileIds: (tiles: DashboardTile[], collapsedTileGroupKeys: string[]) => Set<number>
        insightTiles: (tiles: DashboardTile[]) => DashboardTile[]
        textTiles: (tiles: DashboardTile[]) => DashboardTile[]
        dashboardControlScopes: (insightTiles: DashboardTile[]) => Record<DashboardControl, DashboardControlScope>
        itemsLoading: (
            dashboardLoading: boolean,
            dashboardStreaming: boolean,
            refreshStatus: Record<string, RefreshStatus>,
            initialVariablesLoaded: boolean
        ) => boolean
        isRefreshingQueued: (refreshStatus: Record<string, RefreshStatus>) => (id: string) => boolean
        isRefreshing: (refreshStatus: Record<string, RefreshStatus>) => (id: string) => boolean
        highlightedInsightId: (searchParams: Record<string, any>) => any
        sortedDates: (insightTiles: DashboardTile[], collapsedTileIds: Set<number>) => Dayjs[]
        oldestRefreshed: (sortedDates: Dayjs[], pageVisibility: boolean) => Dayjs | null
        effectiveLastRefresh: (lastDashboardRefresh: Dayjs | null, oldestRefreshed: Dayjs | null) => Dayjs | null
        nextAllowedDashboardRefresh: (lastDashboardRefresh: Dayjs | null) => Dayjs | null
        nextWidgetStaleAt: (
            widgetTiles: DashboardTile[],
            widgetRefreshStatus: Record<
                number,
                {
                    error?: string | null
                    fetchedAt?: number
                    loading?: boolean
                }
            >
        ) => number | null
        blockRefresh: (
            nextAllowedDashboardRefresh: Dayjs | null,
            effectiveLastRefresh: Dayjs | null,
            widgetTiles: DashboardTile[],
            widgetRefreshStatus: Record<
                number,
                {
                    error?: string | null
                    fetchedAt?: number
                    loading?: boolean
                }
            >,
            refreshEligibilityTick: number,
            placement: DashboardPlacement,
            collapsedTileIds: Set<number>,
            pageVisibility: boolean
        ) => boolean
        canEditDashboard: (dashboard: DashboardType | null) => boolean
        canSaveProjectDashboardTemplate: (
            canEditDashboard: boolean,
            asDashboardTemplate: DashboardTemplateEditorType | undefined
        ) => boolean
        canRestrictDashboard: (
            dashboard: DashboardType | null,
            user: null | import('~/types').UserType,
            currentTeam: null | import('~/types').TeamPublicType | import('~/types').TeamType
        ) => boolean
        sizeKey: (columns: number | null) => DashboardLayoutSize | undefined
        layouts: (tiles: DashboardTile[], draftLayouts: Partial<Record<string, Layout>> | null) => ResponsiveLayouts
        layout: (
            layouts: Partial<Record<string, Layout>>,
            sizeKey: DashboardLayoutSize | undefined
        ) => Layout | undefined
        layoutForItem: (layout: Layout | undefined) => Record<string, TileLayout>
        tileGroupSections: (
            tileGroupSectionsEnabled: boolean,
            tiles: DashboardTile[],
            layouts: Partial<Record<string, Layout>>,
            dashboard: DashboardType | null,
            placement: DashboardPlacement
        ) => DashboardSection[]
        tileGroupSectionLayouts: (
            tileGroupSections: DashboardSection[],
            layouts: Partial<Record<string, Layout>>,
            dashboard: DashboardType | null
        ) => SectionLayouts[]
        tileGroupMoveOptions: (
            tileGroupSections: DashboardSection[],
            canEditDashboard: boolean
        ) => Record<number, TileGroupMoveOptions>
        refreshMetrics: (
            refreshStatus: Record<string, RefreshStatus>,
            refreshTilesTotal: number | null
        ) => {
            completed: number
            total: number
        }
        breadcrumbs: (
            dashboard: DashboardType | null,
            error404: boolean,
            dashboardFailedToLoad: boolean,
            searchParams: Record<string, any>
        ) => Breadcrumb[]
        projectTreeRef: (arg: number) => ProjectTreeRef
        hasInvalidDashboardId: (arg: number) => boolean
        sidePanelContext: (dashboard: DashboardType | null) => SidePanelSceneContext | null
        dataColorThemeId: (
            temporaryDataColorThemeId: {
                themeId: number | null
            } | null,
            dashboard: DashboardType | null
        ) => number | null
        dataColorTheme: (
            dataColorThemeId: number | null,
            getTheme: (themeId: number | string | null | undefined) => DataColorTheme | null // dataThemeLogic
        ) => DataColorTheme | null
        autoBreakdownColorsEnabled: (featureFlags: FeatureFlagsSet) => boolean
        breakdownValuesIncomplete: (
            itemsLoading: boolean,
            insightTiles: DashboardTile[],
            waitingTileRefresh: WaitingTileRefresh | null
        ) => boolean
        effectiveBreakdownColors: (
            temporaryBreakdownColors: BreakdownColorConfig[],
            dashboard: DashboardType | null,
            insightTiles: DashboardTile[],
            breakdownValuesIncomplete: boolean,
            autoBreakdownColorsEnabled: boolean,
            dataColorTheme: DataColorTheme | null
        ) => BreakdownColorConfig[]
        hasUnsavedColorChanges: (
            temporaryBreakdownColors: BreakdownColorConfig[],
            temporaryDataColorThemeId: {
                themeId: number | null
            } | null,
            dashboard: DashboardType | null
        ) => boolean
        maxContext: (dashboard: DashboardType | null) => MaxContextInput[]
    }
}

export type dashboardLogicType = MakeLogicType<
    dashboardLogicValues,
    dashboardLogicActions,
    DashboardLogicProps,
    dashboardLogicMeta
>

// Filter edit mode only exists to hold the unsaved-settings controls, so it ends once nothing is
// unsaved. Layout editing carries its own Save and Cancel, so it keeps the dashboard in edit mode.
function exitFilterEditModeWhenSaved(
    values: dashboardLogicType['values'],
    actions: dashboardLogicType['actions']
): void {
    if (values.dashboardSettingsState === 'saved' && values.dashboardEditing?.filters && !values.layoutEditMode) {
        actions.setDashboardEditing(null, DashboardEventSource.DashboardFilters)
    }
}

let dashboardViewedTimeout: ReturnType<typeof setTimeout> | undefined

interface TileMove {
    layout: Layout
    sourceGroupKey: string | null
    groupKey: string | null
    message: string
}

const sectionGroupKey = (section: DashboardSection | null): string | null =>
    section?.kind === 'group' ? section.groupKey : null

const tileMoveMessage = (target: DashboardSection | null): string =>
    target?.kind === 'group'
        ? // The target gains this tile, and an untitled group is named by its tile count.
          `Moved to the "${getTileGroupLabel(target.group, target.tiles.length + 1)}" group`
        : 'Tile taken out of its group'

function placementAfterMove(
    move: TileMove,
    tileId: number
): { sm: Layout[number] | undefined; placement: TilePlacement } {
    const sm = move.layout.find((item) => item.i === tileId.toString())
    return { sm, placement: { layouts: sm ? ({ sm } as DashboardTile['layouts']) : {}, group_key: move.groupKey } }
}

function planTileMove(
    values: dashboardLogicValues,
    tileId: number,
    sectionKey: string | null,
    cell: { x: number; y: number } | null
): TileMove | null {
    const sections = values.tileGroupSections
    const source = sections.find((section) => section.tiles.some((tile) => tile.id === tileId))
    const target = sectionKey === null ? null : sections.find((section) => section.key === sectionKey)
    if (!source || target === undefined || target === source || (!target && source.kind !== 'group')) {
        return null
    }
    const layout = getLayoutAfterTileMove({
        layout: values.layouts.sm ?? [],
        sections,
        sectionLayouts: values.tileGroupSectionLayouts.map((sectionLayouts) => sectionLayouts.sm ?? []),
        tileId,
        target,
        cell,
        compactor: getDashboardGridCompactor(values.dashboard?.customization?.layout_compaction),
    })
    return {
        layout,
        sourceGroupKey: sectionGroupKey(source),
        groupKey: sectionGroupKey(target),
        message: tileMoveMessage(target),
    }
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
            dataRetentionBannerLogic,
            ['warningEligible', 'retentionMonths', 'retentionPeriodLabel'],
            apiStatusLogic,
            ['internetConnectionIssue'],
            dashboardTileGroupChoicesLogic,
            ['tileGroupChoices'],
        ],
        logic: [dashboardsModel, insightsModel, eventUsageLogic, addInsightToDashboardLogic],
    })),

    props({ id: NaN } as DashboardLogicProps),

    key((props) => {
        if (!Number.isFinite(props.id)) {
            return 'invalid'
        }
        return props.id
    }),

    actions(() => ({
        revealHighlightedInsight: true,
        /**
         * Dashboard loading and dashboard tile refreshes.
         */
        loadDashboard: (payload: { action: DashboardLoadAction }) => payload,
        /** Load dashboard with streaming tiles approach. */
        loadDashboardStreaming: (payload: {
            action: DashboardLoadAction
            manualDashboardRefresh?: boolean
            retry?: boolean
        }) => payload,
        /** Dashboard metadata loaded successfully. */
        loadDashboardMetadataSuccess: (dashboard: DashboardType | null) => ({ dashboard }),
        /** Single tile received from stream. */
        receiveTileFromStream: (data: { tile: any; order: number }) => data,
        /** Tile streaming completed. */
        tileStreamingComplete: true,
        /** Tile streaming failed. */
        tileStreamingFailure: (error: any, willRetry: boolean = false) => ({ error, willRetry }),
        /** A failed dashboard stream needs a load error with a retry action. */
        setDashboardStreamFailed: true,
        /** Retry a failed load through the same load path as the initial load. */
        retryDashboardLoad: true,
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
        refreshDashboardItem: (payload: { tile: DashboardTile }) => payload,
        /** Refresh tiles of a loaded dashboard e.g. stale tiles after initial load, previewed tiles after applying filters, etc. */
        refreshDashboardItems: (payload: {
            action: RefreshDashboardItemsAction | DashboardLoadAction
            forceRefresh?: boolean
            previewUnsavedFilters?: boolean
        }) => payload,
        refreshDashboardWidgets: (payload: { tileIds: number[]; forceRefresh?: boolean }) => payload,
        toggleTileGroup: (groupKey: string) => ({ groupKey }),
        refreshTileGroup: (groupKey: string) => ({ groupKey }),
        setWaitingTileRefresh: (waiting: WaitingTileRefresh) => ({ waiting }),
        clearWaitingTileRefresh: (tileIds: number[]) => ({ tileIds }),
        setRevealedTileGroup: (revealedTileGroup: RevealedTileGroup | null) => ({ revealedTileGroup }),
        /** A band grid reports its own layout, which joins the other bands into one dashboard layout. */
        updateTileGroupSectionLayout: (layouts: ResponsiveLayouts) => ({ layouts }),
        /** A null section takes the tile out of its group, and a null cell puts it below the target's tiles. */
        moveTileToSection: (
            tileId: number,
            sectionKey: string | null,
            cell: { x: number; y: number } | null,
            method: TileGroupMoveMethod
        ) => ({ tileId, sectionKey, cell, method }),
        tilePlacementsSaved: (placements: Record<number, TilePlacement>) => ({ placements }),
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
        stopWidgetRefreshes: (tileIds: number[]) => ({ tileIds }),
        addWidgetTiles: (payload: {
            dashboardId: number
            widgets: { widgetType: string; config: Record<string, unknown> }[]
        }) => payload,
        setAddWidgetModalOpen: (open: boolean) => ({ open }),
        toggleAddWidgetSelectedType: (widgetType: string) => ({ widgetType }),
        clearAddWidgetSelectedTypes: true,
        toggleAddWidgetCollapsedGroup: (groupId: string) => ({ groupId }),
        toggleAddWidgetFilteredGroup: (groupId: string) => ({ groupId }),
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
        setDates: (dateFrom: string | null, dateTo: string | null | undefined, explicitDate?: boolean) => ({
            dateFrom,
            dateTo,
            explicitDate,
        }),
        setProperties: (properties: AnyPropertyFilter[] | null) => ({ properties }),
        setBreakdownFilter: (breakdown_filter: BreakdownFilter | null) => ({ breakdown_filter }),
        setInterval: (interval: IntervalType | null) => ({ interval }),
        setFilterTestAccounts: (filterTestAccounts: boolean | null) => ({ filterTestAccounts }),
        setCompareFilter: (compareFilter: CompareFilter | null) => ({ compareFilter }),
        reportDashboardFilterChange: (
            changeType: DashboardFilterChangeType,
            properties: Record<string, string | number | boolean | null | undefined>
        ) => ({ changeType, properties }),
        setMetricVariables: (metricVariables: MetricsDashboardVariable[] | null) => ({ metricVariables }),
        setExternalFilters: (filters: DashboardFilter) => ({ filters }),
        setDashboardSettingsDraft: (settings: DashboardSettings | null) => ({ settings }),
        setPreviewedDashboardSettings: (settings: DashboardSettings | null) => ({ settings }),
        setInitialDashboardSettingsOverride: (settings: DashboardSettings) => ({ settings }),
        clearInitialDashboardSettingsOverride: true,
        clearDashboardSettingsUrlOverrides: true,
        previewDashboardChanges: true,
        previewDashboardChangesFailure: true,
        saveDashboardChanges: true,
        saveDashboardChangesSuccess: (dashboard: DashboardType | null, settings: DashboardSettings | null) => ({
            dashboard,
            settings,
        }),
        saveDashboardChangesFailure: (error: string) => ({ error }),
        discardDashboardChanges: true,
        saveDashboardColorChanges: true,
        saveLayoutChanges: true,
        discardLayoutChanges: true,
        saveEditModeChanges: (scope: DashboardEditSaveScope) => ({ scope }),
        saveLayout: true,
        resetUrlFilters: () => true,
        resetUrlVariables: true,
        recheckRefreshEligibility: true,
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
        saveDashboardTileSpacing: (tileSpacing: DashboardTileSpacing) => ({ tileSpacing }),
        saveDashboardGridCompaction: (layoutCompaction: DashboardGridCompaction) => ({ layoutCompaction }),
        setDashboardCustomizeMenuOpen: (open: boolean) => ({ open }),
        changeDashboardGridCompaction: (layoutCompaction: DashboardGridCompaction) => ({ layoutCompaction }),
        changeDashboardTileSpacing: (tileSpacing: DashboardTileSpacing) => ({ tileSpacing }),
        updateDashboardTags: (tags: string[]) => ({ tags }),
        /** Update page visibility for virtualized rendering. */
        setPageVisibility: (visible: boolean) => ({ visible }),
        setSubscriptionMode: (enabled: boolean, id?: number | 'new') => ({ enabled, id }),
        /** Set the dashboard mode, see DashboardMode for details. */
        setDashboardMode: (mode: DashboardMode | null, source: DashboardEventSource) => ({ mode, source }),
        setDashboardEditing: (editing: DashboardEditing | null, source: DashboardEventSource) => ({ editing, source }),
        /** Exit edit mode, prompting to confirm if there are unsaved changes. */
        cancelLayoutEdit: true,
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
        stageLayouts: (layouts: ResponsiveLayouts) => ({ layouts }),
        clearDraftLayouts: () => true,
        applyDashboardUpdate: (dashboard: DashboardType, savedPlacements: Record<number, TilePlacement>) => ({
            dashboard,
            savedPlacements,
        }),
        updateContainerWidth: (containerWidth: number, columns: number) => ({ containerWidth, columns }),
        updateTileColor: (tileId: number, color: InsightColor | null) => ({ tileId, color }),
        toggleTileDescription: (tileId: number) => ({ tileId }),
        setTileProperty: (
            tileId: number,
            properties: Partial<Pick<DashboardTile, 'color' | 'group_key' | 'layouts' | 'show_description'>>
        ) => ({
            tileId,
            properties,
        }),
        duplicateTile: (tile: DashboardTile) => ({ tile }),
        removeTile: (tile: DashboardTile) => ({ tile }),
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
        copyToDashboard: (
            tile: DashboardTile,
            fromDashboard: number,
            toDashboard: number,
            toDashboardName: string
        ) => ({
            tile,
            fromDashboard,
            toDashboard,
            toDashboardName,
        }),
        setTextTileId: (textTileId: DashboardTileIdOrNew) => ({ textTileId }),
        setButtonTileId: (buttonTileId: DashboardTileIdOrNew) => ({ buttonTileId }),
        openAddInsightModal: true,
        openTextTileModal: true,
        openImageTileModal: true,
        openButtonTileModal: true,
        closeTileModal: true,
        setTileOverride: (tile: DashboardTile) => ({ tile }),

        /**
         * Usage tracking.
         */
        setShouldReportOnAPILoad: (shouldReport: boolean) => ({ shouldReport }), // See reducer for details
        reportDashboardViewed: true, // Reports `viewed dashboard` and `dashboard analyzed` events
        reportDashboardViewedEvent: (dashboard: DashboardType, lastRefreshed: Dayjs | null, delay?: number) => ({
            dashboard,
            lastRefreshed,
            delay,
        }),
        reportInsightsViewed: (insights: InsightModel[]) => ({ insights }),

        /**
         * Dashboard result colors.
         */
        setBreakdownColorConfig: (config: BreakdownColorConfig) => ({ config }),
        setDataColorThemeId: (dataColorThemeId: number | null) => ({ dataColorThemeId }),
        setDashboardTileSpacing: (tileSpacing: DashboardTileSpacing) => ({ tileSpacing }),
        setDashboardGridCompaction: (layoutCompaction: DashboardGridCompaction) => ({ layoutCompaction }),
        setDashboardTileSpacingSaving: (saving: boolean) => ({ saving }),
        restoreTemporaryColorState: (colors: BreakdownColorConfig[], themeId: { themeId: number | null } | null) => ({
            colors,
            themeId,
        }),

        setLoadLayoutFromServerOnPreview: (loadLayoutFromServerOnPreview: boolean) => ({
            loadLayoutFromServerOnPreview,
        }),
        dashboardNotFound: true,
    })),

    loaders(({ actions, props, values, cache }) => ({
        dashboard: [
            null as DashboardType | null,
            {
                loadDashboard: async ({ action }, breakpoint) => {
                    actions.loadingDashboardItemsStarted(action)

                    await breakpoint(200)

                    try {
                        const apiUrl = values.apiUrl(
                            'force_cache',
                            values.filtersOverrideForRequests,
                            values.currentDashboardVariables
                        )
                        // nosemgrep: prefer-codegen-api -- Legacy raw API call with a URL built at runtime and an unchecked response type. Use a generated function if one covers this endpoint.
                        const dashboardResponse: Response = await api.getResponse(apiUrl)
                        const dashboard: DashboardType | null = await getJSONOrNull(dashboardResponse)

                        actions.setInitialLoadResponseBytes(getResponseBytes(dashboardResponse))

                        if (!dashboard || typeof dashboard !== 'object' || typeof dashboard.id !== 'number') {
                            throw new Error('Dashboard response was empty or invalid')
                        }

                        return dashboard
                    } catch (error: any) {
                        if (error.status === 404) {
                            return null
                        }
                        if (isAccessDeniedError(error)) {
                            actions.setAccessDeniedToDashboard()
                        }
                        throw error
                    }
                },
                loadDashboardStreaming: async ({ action, retry }, breakpoint) => {
                    actions.loadingDashboardItemsStarted(action)
                    await breakpoint(200)
                    // fetchEventSource retries the failed stream on its own. If that stream delivered metadata during
                    // the wait, a new stream would abort it and replace the loaded dashboard with null.
                    if (retry && !values.dashboardFailedToLoad) {
                        return values.dashboard
                    }
                    let metadataReceived = false
                    const preserveTiles = retry && !!values.dashboard?.tiles?.length
                    let retriedDashboard: DashboardType | null = null
                    cache.disposables.dispose('dashboardStream')
                    cache.dashboardStreamActive = true

                    // nosemgrep: prefer-codegen-api-namespaced-dashboards -- The generated void client cannot handle SSE messages, retries, and cancellation.
                    const disposeStream = await api.dashboards.streamTiles(
                        props.id,
                        {
                            layoutSize: values.currentLayoutSize,
                            filtersOverride: values.filtersOverrideForRequests,
                            variablesOverride: values.currentDashboardVariables,
                        },
                        // onMessage callback - handles both metadata and tiles
                        (data) => {
                            if (data.type === 'metadata') {
                                metadataReceived = true
                                if (preserveTiles) {
                                    // Keep readable tiles until a complete replacement is available, even if retry fails.
                                    retriedDashboard = { ...data.dashboard, tiles: [...(data.dashboard.tiles ?? [])] }
                                } else {
                                    actions.loadDashboardMetadataSuccess(data.dashboard as DashboardType)
                                }
                            } else if (data.type === 'tile') {
                                if (retriedDashboard) {
                                    retriedDashboard.tiles.push(data.tile)
                                } else {
                                    actions.receiveTileFromStream(data)
                                }
                            }
                        },
                        // onComplete callback
                        () => {
                            cache.dashboardStreamActive = false
                            if (metadataReceived) {
                                if (retriedDashboard) {
                                    actions.loadDashboardMetadataSuccess(retriedDashboard)
                                }
                                actions.tileStreamingComplete()
                            } else {
                                actions.tileStreamingFailure(
                                    new Error('Dashboard stream completed without dashboard metadata.')
                                )
                            }
                        },
                        // onError callback
                        (error, willRetry = false) => {
                            cache.dashboardStreamActive = willRetry
                            console.error('❌ Tile streaming error:', error)
                            actions.tileStreamingFailure(error, willRetry)
                        }
                    )
                    cache.disposables.add(
                        () => () => {
                            cache.dashboardStreamActive = false
                            disposeStream()
                        },
                        'dashboardStream',
                        { pauseOnPageHidden: false }
                    )

                    return preserveTiles ? values.dashboard : null
                },
                saveEditModeChanges: ({ scope }) =>
                    enqueueEditSave({ cache, mount: (): (() => void) => dashboardLogic(props).mount() }, async () => {
                        cache.dashboardChangesPersisted = false
                        cache.draftLayoutsAtSave = values.draftLayouts
                        try {
                            // Only persist sm layouts; xs layouts are derived on the fly
                            const draftByTile = values.draftLayouts ? layoutsByTile(values.layouts) : null
                            const layoutsToUpdate = (values.dashboard?.tiles || []).map((tile) => {
                                const sm = draftByTile?.[tile.id]?.sm ?? tile.layouts?.sm
                                return {
                                    id: tile.id,
                                    layouts: sm ? { sm } : {},
                                    ...groupKeyUpdate(tile, values.savedTilePlacements[tile.id]),
                                }
                            })

                            const currentDashboard = values.dashboard
                            if (!currentDashboard) {
                                return null
                            }

                            const persistedBreakdownColors = currentDashboard.breakdown_colors || []
                            const persistedThemeId = currentDashboard.data_color_theme_id ?? null

                            // While tiles are still loading, or an errored/aborted tile is missing its
                            // results, the visible breakdown values are incomplete, so fresh auto
                            // assignments and stale-entry pruning would both act on partial data.
                            // Persist only the saved colors with unsaved edits merged over them, and
                            // leave materializing auto entries to a save with every tile's values known.
                            const breakdownColorsToSave = values.breakdownValuesIncomplete
                                ? mergeBreakdownColorConfigs(
                                      values.temporaryBreakdownColors,
                                      persistedBreakdownColors
                                  ).filter((config) => !!config.colorToken)
                                : values.effectiveBreakdownColors
                            const breakdownColorsChanged = !equal(persistedBreakdownColors, breakdownColorsToSave)
                            const themeChanged = (values.dataColorThemeId ?? null) !== persistedThemeId

                            const layoutsChanged = (currentDashboard.tiles || []).some((tile) => {
                                const originalLayouts = values.savedTilePlacements[tile.id]?.layouts?.sm
                                const updatedLayouts = layoutsToUpdate.find((t) => t.id === tile.id)?.layouts?.sm
                                return (
                                    !equal(originalLayouts || {}, updatedLayouts || {}) ||
                                    tileGroupChanged(tile, values.savedTilePlacements[tile.id])
                                )
                            })

                            const colorsChanged = breakdownColorsChanged || themeChanged
                            const hasChanges = scope === 'colors' ? colorsChanged : layoutsChanged
                            if (!hasChanges) {
                                return currentDashboard
                            }

                            const payload =
                                scope === 'colors'
                                    ? {
                                          breakdown_colors: breakdownColorsToSave,
                                          data_color_theme_id: values.dataColorThemeId,
                                      }
                                    : {
                                          tiles: layoutsToUpdate,
                                      }
                            // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                            const persistedDashboard: DashboardType = await api.update(
                                `api/projects/${values.currentTeamId}/dashboards/${props.id}`,
                                payload
                            )
                            const latestDashboard = values.dashboard ?? currentDashboard
                            const updatedDashboard =
                                scope === 'colors'
                                    ? { ...persistedDashboard, tiles: latestDashboard.tiles }
                                    : {
                                          ...persistedDashboard,
                                          breakdown_colors: latestDashboard.breakdown_colors,
                                          data_color_theme_id: latestDashboard.data_color_theme_id,
                                      }
                            updatedDashboard.persisted_filters = latestDashboard.persisted_filters
                            updatedDashboard.persisted_variables = latestDashboard.persisted_variables
                            if (scope === 'colors') {
                                dashboardsModel.actions.updateDashboardSuccess(
                                    {
                                        ...persistedDashboard,
                                        persisted_filters: latestDashboard.persisted_filters,
                                        persisted_variables: latestDashboard.persisted_variables,
                                    },
                                    { layoutsPersisted: true }
                                )
                            } else {
                                actions.tilePlacementsSaved(tilePlacementsFromDashboard(updatedDashboard))
                            }
                            if (scope === 'colors' && breakdownColorsChanged) {
                                const autoCount = breakdownColorsToSave.filter(
                                    (color) => color.source === 'auto'
                                ).length
                                posthog.capture('dashboard breakdown colors saved', {
                                    dashboard_id: values.dashboard?.id,
                                    dashboard: sanitizeDashboard(values.dashboard),
                                    manual_count: breakdownColorsToSave.length - autoCount,
                                    auto_count: autoCount,
                                    breakdown_types: Array.from(
                                        new Set(breakdownColorsToSave.map((c) => String(c.breakdownType)))
                                    ),
                                })
                            }
                            if (scope === 'colors' && themeChanged) {
                                posthog.capture('dashboard color theme set', {
                                    dashboard_id: values.dashboard?.id,
                                    dashboard: sanitizeDashboard(values.dashboard),
                                    theme_id: values.dataColorThemeId,
                                })
                            }
                            cache.dashboardChangesPersisted = true
                            return updatedDashboard
                        } catch (e) {
                            lemonToast.error('Could not update dashboard: ' + String(e))
                            return values.dashboard
                        }
                    }),
                removeTile: async ({ tile }) => {
                    // The reducer drops the tile optimistically; here we only persist and roll back on failure.
                    try {
                        // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                        await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
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
                        } as DashboardType
                    }
                },
                duplicateTile: async ({ tile }): Promise<DashboardType> => {
                    try {
                        const newTile = { ...tile } as Partial<DashboardTile>
                        if (newTile.text) {
                            newTile.text = {
                                body: newTile.text.body,
                                agent_context: newTile.text.agent_context,
                            } as TextModel
                        }

                        const { duplicateLayouts, tilesToUpdate } = calculateDuplicateLayout(values.layouts, tile.id)

                        // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                        const dashboard: DashboardType = await api.update(
                            `api/projects/${values.currentTeamId}/dashboards/${props.id}`,
                            {
                                duplicate_tiles: [{ ...newTile, layouts: duplicateLayouts }],
                                tiles: tilesToUpdate.length > 0 ? tilesToUpdate : undefined,
                            }
                        )
                        // The server copy lacks unsaved group moves, so keep each tile's group from before.
                        const groupKeys = new Map(values.tiles.map((tile) => [tile.id, tile.group_key ?? null]))
                        return {
                            ...dashboard,
                            tiles: dashboard.tiles.map((tile) =>
                                groupKeys.has(tile.id) ? { ...tile, group_key: groupKeys.get(tile.id) } : tile
                            ),
                        }
                    } catch (e) {
                        // Re-throw so duplicateTileFailure fires. Swallowing the error resolved it as a
                        // success, so the tile refreshed with no copy and the user kept clicking.
                        lemonToast.error(e instanceof ApiError ? (e.detail ?? e.message) : 'Could not duplicate tile')
                        throw e
                    }
                },
                moveToDashboard: async ({ tile, fromDashboard, toDashboard }) => {
                    if (!tile || fromDashboard === toDashboard) {
                        return values.dashboard
                    }

                    if (fromDashboard !== props.id) {
                        return values.dashboard
                    }
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. dashboardsMoveTilePartialUpdate() from 'products/dashboards/frontend/generated/api' serves this route, but its generated types do not describe this call yet, so fix the endpoint's OpenAPI schema first.
                    const dashboard: DashboardType = await api.update(
                        `api/projects/${teamLogic.values.currentTeamId}/dashboards/${props.id}/move_tile`,
                        {
                            tile,
                            to_dashboard: toDashboard,
                        }
                    )
                    return dashboard
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
                        // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. dashboardsCopyTileCreate() from 'products/dashboards/frontend/generated/api' serves this route, but its generated types do not describe this call yet, so fix the endpoint's OpenAPI schema first.
                        const destination = await api.create<DashboardType | null>(
                            `api/projects/${teamLogic.values.currentTeamId}/dashboards/${toDashboard}/copy_tile`,
                            { fromDashboardId: fromDashboard, tileId: tile.id }
                        )

                        if (tile.insight) {
                            const insight = tile.insight
                            // The copy is a new tile, so its id comes from the destination dashboard.
                            const copiedTile = destination?.tiles?.find((t) => t.insight?.id === insight.id)
                            const nextDashboardTiles =
                                copiedTile && !liveDashboardIds(insight.dashboard_tiles).includes(toDashboard)
                                    ? [
                                          ...(insight.dashboard_tiles || []),
                                          { id: copiedTile.id, dashboard_id: toDashboard },
                                      ]
                                    : insight.dashboard_tiles
                            dashboardsModel.actions.updateDashboardInsight(
                                { ...insight, dashboard_tiles: nextDashboardTiles },
                                [toDashboard]
                            )
                        }

                        posthog.capture('dashboard widget copied to other dashboard', {
                            from_dashboard_id: fromDashboard,
                            to_dashboard_id: toDashboard,
                            tile_type: widgetType,
                        })

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
                    tile: DashboardTile
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
                        dashboardsModel.actions.updateDashboardSuccess(
                            mergeUpdatedWidgetTileIntoDashboard(values.dashboard, updatedTile)
                        )
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
        dashboardFiltersSaving: [
            false,
            {
                saveDashboardChanges: () => true,
                saveDashboardChangesSuccess: () => false,
                saveDashboardChangesFailure: () => false,
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
        dashboardTileSpacingSaving: [
            false,
            {
                setDashboardTileSpacingSaving: (_, { saving }) => saving,
            },
        ],
        loadingPreview: [
            false,
            {
                setDates: () => false,
                setProperties: () => false,
                setBreakdownFilter: () => false,
                setInterval: () => false,
                setFilterTestAccounts: () => false,
                setCompareFilter: () => false,
                setMetricVariables: () => false,
                overrideVariableValue: () => false,
                loadDashboardSuccess: () => false,
                loadDashboardFailure: () => false,
                previewDashboardChanges: () => true,
                previewDashboardChangesFailure: () => false,
                setPreviewedDashboardSettings: (_, { settings }) => settings !== null,
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
                dashboardNotFound: () => false,
                loadDashboard: () => false,
                loadDashboardStreaming: () => false,
                loadDashboardSuccess: () => false,
                loadDashboardMetadataSuccess: () => false,
            },
        ],
        dashboardFailedToLoad: [
            false,
            {
                // A new load keeps the error state mounted, so a retry shows its loading state
                // and a failed retry does not flash the error state off and on.
                loadDashboardSuccess: () => false,
                // The stream auto-retries after transient errors; delivered metadata means it recovered,
                // so clear the load-error state instead of leaving it latched over a loaded dashboard.
                loadDashboardMetadataSuccess: () => false,
                dashboardNotFound: () => false,
                setAccessDeniedToDashboard: () => false,
                loadDashboardFailure: () => true,
                setDashboardStreamFailed: () => true,
            },
        ],
        savedTilePlacements: [
            {} as Record<DashboardTile['id'], TilePlacement>,
            {
                loadDashboardSuccess: (_, { dashboard }) => tilePlacementsFromDashboard(dashboard),
                loadDashboardMetadataSuccess: (_, { dashboard }) => tilePlacementsFromDashboard(dashboard),
                applyDashboardUpdate: (_, { savedPlacements }) => savedPlacements,
                // Not saveEditModeChangesSuccess, because a failed save also fires it and the moves must stay unsaved.
                tilePlacementsSaved: (state, { placements }) => ({ ...state, ...placements }),
                receiveTileFromStream: (state, { tile }) => ({ ...state, [tile.id]: tilePlacement(tile) }),
                duplicateTileSuccess: (state, { dashboard }) =>
                    dashboard ? { ...tilePlacementsFromDashboard(dashboard), ...state } : state,
            },
        ],
        draftLayouts: [
            null as ResponsiveLayouts | null,
            {
                stageLayouts: (_, { layouts }) => layouts,
                clearDraftLayouts: () => null,
                updateLayouts: () => null,
                loadDashboardSuccess: () => null,
                loadDashboardMetadataSuccess: () => null,
                setDashboardEditing: (state, { editing, source }) =>
                    editing === null && source === DashboardEventSource.DashboardHeaderDiscardChanges ? null : state,
            },
        ],
        // Unsaved color edits only — merged over dashboard.breakdown_colors in effectiveBreakdownColors
        temporaryBreakdownColors: [
            [] as BreakdownColorConfig[],
            {
                setBreakdownColorConfig: (state, { config }) => {
                    const existingConfigIndex = state.findIndex((c) => breakdownConfigIdentityMatches(c, config))
                    if (existingConfigIndex >= 0) {
                        return [...state.slice(0, existingConfigIndex), config, ...state.slice(existingConfigIndex + 1)]
                    }
                    return [...state, config]
                },
                // Cleared on discard only. After a successful save the edits match what's persisted,
                // and a failed save (which also fires saveEditModeChangesSuccess) must keep them.
                setDashboardEditing: (state, { source }) =>
                    source === DashboardEventSource.DashboardHeaderDiscardChanges ? [] : state,
                restoreTemporaryColorState: (_, { colors }) => colors,
            },
        ],
        // Unsaved theme edit; null means untouched, so clearing the theme is distinguishable
        temporaryDataColorThemeId: [
            null as { themeId: number | null } | null,
            {
                setDataColorThemeId: (_, { dataColorThemeId }) => ({ themeId: dataColorThemeId || null }),
                setDashboardEditing: (state, { source }) =>
                    source === DashboardEventSource.DashboardHeaderDiscardChanges ? null : state,
                restoreTemporaryColorState: (_, { themeId }) => themeId,
            },
        ],
        // A highlight link opens the group of its tile for this visit only, so it never changes the viewer's choice.
        revealedTileGroup: [
            null as RevealedTileGroup | null,
            {
                setRevealedTileGroup: (_, { revealedTileGroup }) => revealedTileGroup,
                [dashboardTileGroupChoicesLogic.actionTypes.setTileGroupCollapsed]: (
                    state,
                    { dashboardId, groupKey }
                ) =>
                    state && dashboardId === props.id && groupKey === state.groupKey
                        ? { ...state, groupKey: null }
                        : state,
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
            null as DashboardType | null,
            {
                dashboardNotFound: () => null,
                setAccessDeniedToDashboard: () => null,
                applyDashboardUpdate: (_, { dashboard }) => dashboard,
                updateLayouts: (state, { layouts }) => {
                    const itemLayouts = layoutsByTile(layouts)

                    // Only persist sm layouts; xs layouts are derived on the fly
                    return {
                        ...state,
                        tiles: state?.tiles?.map((tile) => ({
                            ...tile,
                            layouts: itemLayouts[tile.id]?.sm ? { sm: itemLayouts[tile.id].sm } : {},
                        })),
                    } as DashboardType
                },
                setTileProperty: (state, { tileId, properties }) => {
                    return {
                        ...state,
                        tiles: state?.tiles?.map((tile) => (tile.id === tileId ? { ...tile, ...properties } : tile)),
                    } as DashboardType
                },
                setDashboardTileSpacing: (state, { tileSpacing }) =>
                    state
                        ? {
                              ...state,
                              customization: { ...state.customization, tile_spacing: tileSpacing },
                          }
                        : state,
                setDashboardGridCompaction: (state, { layoutCompaction }) =>
                    state
                        ? {
                              ...state,
                              customization: { ...state.customization, layout_compaction: layoutCompaction },
                          }
                        : state,
                removeTile: (state, { tile }) => {
                    // Optimistically drop the tile so the grid reflows immediately; the loader rolls back on failure.
                    return {
                        ...state,
                        tiles: state?.tiles?.filter((t) => t.id !== tile.id),
                    } as DashboardType
                },
                [dashboardsModel.actionTypes.tileMovedToDashboard]: (state, { tile, dashboardId }) => {
                    if (state && state.id === dashboardId) {
                        return {
                            ...state,
                            tiles: [...state.tiles, tile],
                        }
                    }
                    return state
                },
                [dashboardsModel.actionTypes.updateDashboardInsight]: (
                    state,
                    {
                        insight,
                        extraDashboardIds,
                        sourceDashboardId,
                    }: {
                        insight: InsightModel
                        extraDashboardIds?: number[]
                        sourceDashboardId?: number
                    }
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
                        const insightIsOnThisDashboard = liveDashboardIds(insight.dashboard_tiles).includes(props.id)
                        const tileIndex = state.tiles.findIndex(
                            (t) => !!t.insight && t.insight.short_id === insight.short_id
                        )

                        const newTiles = state.tiles.slice()

                        if (tileIndex >= 0) {
                            if (insightIsOnThisDashboard) {
                                newTiles[tileIndex] = {
                                    ...newTiles[tileIndex],
                                    insight: insight,
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
                saveDashboardChangesSuccess: (state, { dashboard }) =>
                    state && dashboard
                        ? {
                              ...state,
                              persisted_filters: dashboard.persisted_filters,
                              persisted_variables: dashboard.persisted_variables,
                          }
                        : state,
                [insightsModel.actionTypes.renameInsightSuccess]: (state, { item }): DashboardType | null => {
                    const tileIndex = state?.tiles.findIndex((t) => !!t.insight && t.insight.short_id === item.short_id)
                    const tiles = state?.tiles.slice(0)

                    if (tileIndex === undefined || tileIndex === -1 || !tiles) {
                        return state
                    }

                    // A bare PATCH (rename, display-option persist) doesn't recompute the insight, so
                    // its response carries `result: null` and stale-but-empty cache metadata. Keep the
                    // tile's already-computed chart data instead of blanking it into "Chart data didn't load".
                    // SQL insights draw from `columns` and `types` rather than `result`, so those have to
                    // survive the merge too or the tile loses the columns it picks its axes from.
                    const existing = tiles[tileIndex].insight as InsightModel
                    tiles[tileIndex] = {
                        ...tiles[tileIndex],
                        insight: {
                            ...existing,
                            ...item,
                            result: item.result ?? existing.result,
                            last_refresh: item.last_refresh ?? existing.last_refresh,
                            columns: item.columns ?? existing.columns,
                            types: item.types ?? existing.types,
                            query_scan: item.query_scan ?? existing.query_scan,
                            warnings: item.warnings ?? existing.warnings,
                        },
                    }

                    return {
                        ...state,
                        tiles,
                    } as DashboardType
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

                    return {
                        ...state,
                        tiles: [...state.tiles, tile],
                    } as DashboardType
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
        // Kept when a viewer cancels a refresh, so a group opened later still loads with that refresh's settings.
        waitingTileRefresh: [
            null as WaitingTileRefresh | null,
            {
                setWaitingTileRefresh: (_, { waiting }) => (waiting.tileIds.length > 0 ? waiting : null),
                clearWaitingTileRefresh: (state, { tileIds }) => {
                    const remaining = state?.tileIds.filter((tileId) => !tileIds.includes(tileId)) ?? []
                    return state && remaining.length > 0 ? { ...state, tileIds: remaining } : null
                },
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
        dashboardEditing: [
            null as DashboardEditing | null,
            {
                setDashboardEditing: (_, { editing }) => editing,
            },
        ],
        dashboardCustomizeMenuOpen: [
            false,
            {
                setDashboardCustomizeMenuOpen: (_, { open }) => open,
                setDashboardMode: () => false,
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
        pendingInsertion: [
            null as PendingInsertion | null,
            {
                setPendingInsertion: (_, { pendingInsertion }) => pendingInsertion,
                setDashboardEditing: (state, { editing }) => (editing != null ? null : state),
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
                closeTileModal: () => false,
                setTextTileId: (_, { textTileId }) => !!textTileId,
                openTextTileModal: () => true,
            },
        ],
        showImageTileModal: [
            false,
            {
                closeTileModal: () => false,
                openImageTileModal: () => true,
                setTextTileId: () => false,
            },
        ],
        textTileId: [
            null as DashboardTileIdOrNew,
            {
                closeTileModal: () => null,
                setTextTileId: (_, { textTileId }) => textTileId,
                openTextTileModal: () => null,
            },
        ],

        showButtonTileModal: [
            false,
            {
                closeTileModal: () => false,
                setButtonTileId: (_, { buttonTileId }) => !!buttonTileId,
                openButtonTileModal: () => true,
            },
        ],
        buttonTileId: [
            null as DashboardTileIdOrNew,
            {
                closeTileModal: () => null,
                setButtonTileId: (_, { buttonTileId }) => buttonTileId,
                openButtonTileModal: () => null,
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
                setAccessDeniedToDashboard: () => false,
                loadDashboard: () => false,
                loadDashboardStreaming: () => false,
                loadDashboardSuccess: () => false,
                loadDashboardMetadataSuccess: () => false,
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
        externalFilters: [
            {} as DashboardFilter,
            {
                setExternalFilters: (_: DashboardFilter, { filters }: { filters: DashboardFilter }) => filters,
            },
        ],

        dashboardSettingsDraft: [
            null as DashboardSettings | null,
            {
                setDashboardSettingsDraft: (_, { settings }) => settings,
                saveDashboardChangesSuccess: (state, { settings }) => {
                    if (!state || !settings || equal(state, settings)) {
                        return null
                    }
                    return state
                },
                discardDashboardChanges: () => null,
            },
        ],
        previewedDashboardSettings: [
            null as DashboardSettings | null,
            {
                setPreviewedDashboardSettings: (_, { settings }) => settings,
                saveDashboardChangesSuccess: () => null,
            },
        ],
        initialDashboardSettingsOverride: [
            {
                filters: parseURLFilters(router.values.searchParams),
                variables: {},
            } as DashboardSettings,
            {
                setInitialDashboardSettingsOverride: (_, { settings }) => settings,
                clearInitialDashboardSettingsOverride: () => ({ filters: {}, variables: {} }),
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
                                ? { ...state[tileId], loading: true, error: null }
                                : {
                                      ...state[tileId],
                                      loading: false,
                                      error: error ?? null,
                                      fetchedAt: error ? state[tileId]?.fetchedAt : Date.now(),
                                  },
                        ])
                    ),
                }),
                setWidgetRunResults: (state, { results }) => {
                    const next = { ...state }
                    for (const tileId of Object.keys(results).map(Number)) {
                        next[tileId] = {
                            ...next[tileId],
                            loading: false,
                            fetchedAt: results[tileId].error ? next[tileId]?.fetchedAt : Date.now(),
                        }
                    }
                    return next
                },
                // A stopped load fetched nothing, so the tile keeps its last fetch time.
                stopWidgetRefreshes: (state, { tileIds }) => ({
                    ...state,
                    ...Object.fromEntries(tileIds.map((tileId) => [tileId, { ...state[tileId], loading: false }])),
                }),
            },
        ],
        refreshEligibilityTick: [0, { recheckRefreshEligibility: (state) => state + 1 }],
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
        addWidgetFilteredGroups: [
            [] as string[],
            {
                setAddWidgetModalOpen: (state, { open }) => (open ? [] : state),
                toggleAddWidgetFilteredGroup: (state, { groupId }) => {
                    const filtered = new Set(state)
                    if (filtered.has(groupId)) {
                        filtered.delete(groupId)
                    } else {
                        filtered.add(groupId)
                    }
                    return Array.from(filtered)
                },
            },
        ],
    })),
    selectors(() => ({
        filterEditModeActive: [
            (s) => [s.dashboardEditing],
            (dashboardEditing: DashboardEditing | null): boolean => dashboardEditing?.filters === true,
        ],
        layoutEditMode: [
            (s) => [s.dashboardEditing],
            (dashboardEditing: DashboardEditing | null): boolean => dashboardEditing?.layout === true,
        ],
        shouldUseStreaming: [
            (s) => [s.featureFlags],
            (featureFlags: import('lib/logic/featureFlagLogic').FeatureFlagsSet): boolean => {
                const hasFeatureFlag = !!featureFlags[FEATURE_FLAGS.SSE_DASHBOARDS]
                const hasSSESupport = typeof EventSource !== 'undefined'
                return hasFeatureFlag && hasSSESupport
            },
        ],
        canAutoPreview: [
            (s) => [s.insightTiles],
            (insightTiles: DashboardTile[]): boolean => insightTiles.length < AUTO_PREVIEW_TILE_LIMIT,
        ],
        savedDashboardSettings: [
            (s) => [s.dashboard],
            (dashboard: DashboardType | null): DashboardSettings => ({
                filters: dashboard?.persisted_filters || {},
                variables: dashboard?.persisted_variables || {},
            }),
        ],
        currentDashboardSettings: [
            (s) => [s.savedDashboardSettings, s.initialDashboardSettingsOverride, s.dashboardSettingsDraft],
            (
                saved: DashboardSettings,
                initialOverride: DashboardSettings,
                draft: DashboardSettings | null
            ): DashboardSettings =>
                draft || {
                    filters: combineSavedAndUrlFilters(saved.filters, initialOverride.filters),
                    variables: { ...saved.variables, ...initialOverride.variables },
                },
        ],
        settingsForRefresh: [
            (s) => [s.savedDashboardSettings, s.initialDashboardSettingsOverride, s.previewedDashboardSettings],
            (
                saved: DashboardSettings,
                initialOverride: DashboardSettings,
                previewed: DashboardSettings | null
            ): DashboardSettings =>
                previewed || {
                    filters: combineSavedAndUrlFilters(saved.filters, initialOverride.filters),
                    variables: { ...saved.variables, ...initialOverride.variables },
                },
        ],
        dashboardSettingsState: [
            (s) => [s.savedDashboardSettings, s.currentDashboardSettings, s.variables],
            (saved: DashboardSettings, current: DashboardSettings, variables: Variable[]): DashboardSettingsState => {
                const variableDefaults = Object.fromEntries(
                    variables.map((variable) => [
                        variable.id,
                        { value: variable.default_value, isNull: variable.isNull },
                    ])
                )
                const variableIds = new Set([...Object.keys(saved.variables), ...Object.keys(current.variables)])
                const variablesChanged = Array.from(variableIds).some(
                    (variableId) =>
                        !dashboardVariableValuesEqual(
                            saved.variables[variableId] ?? variableDefaults[variableId],
                            current.variables[variableId] ?? variableDefaults[variableId]
                        )
                )

                if (!dashboardFiltersEqual(saved.filters, current.filters) || variablesChanged) {
                    return 'unsavedChanges'
                }
                return 'saved'
            },
        ],
        showApplyFiltersBanner: [
            (s) => [s.canAutoPreview, s.dashboardSettingsState],
            (canAutoPreview: boolean, state: DashboardSettingsState) => !canAutoPreview && state === 'unsavedChanges',
        ],
        urlFilters: [
            () => [router.selectors.searchParams],
            (searchParams: Record<string, any>) => parseURLFilters(searchParams),
        ],
        filtersOverrideForLoad: [
            (s) => [s.externalFilters, s.currentDashboardSettings],
            (externalFilters: DashboardFilter, settings: DashboardSettings) =>
                combineDashboardFilters(settings.filters, externalFilters),
        ],
        filtersOverrideForRequests: [
            (s) => [s.filtersOverrideForLoad, s.savedDashboardSettings],
            (filters: DashboardFilter, saved: DashboardSettings): DashboardFilter =>
                withCompactMetricVariables(filters, saved.filters.metricVariables ?? []),
        ],
        effectiveEditBarFilters: [
            (s) => [s.externalFilters, s.currentDashboardSettings],
            (externalFilters: DashboardFilter, settings: DashboardSettings) => {
                const effectiveEditBarFilters = combineDashboardFilters(settings.filters, externalFilters)
                return effectiveEditBarFilters
            },
        ],
        persistableDashboardFilters: [
            (s) => [s.currentDashboardSettings],
            (settings: DashboardSettings) => settings.filters,
        ],
        filtersDirty: [
            (s) => [s.dashboardSettingsState, s.dashboard, s.persistableDashboardFilters],
            (
                state: DashboardSettingsState,
                dashboard: DashboardType | null,
                persistableDashboardFilters: DashboardFilter
            ): boolean =>
                state === 'unsavedChanges' && !equal(dashboard?.persisted_filters || {}, persistableDashboardFilters),
        ],
        variablesDirty: [
            (s) => [s.dashboardSettingsState, s.dashboard, s.currentDashboardVariables],
            (
                state: DashboardSettingsState,
                dashboard: DashboardType | null,
                variables: {
                    [x: string]: HogQLVariable
                }
            ): boolean => state === 'unsavedChanges' && !equal(dashboard?.persisted_variables || {}, variables),
        ],
        filterChanges: [
            (s) => [s.dashboard, s.persistableDashboardFilters],
            (dashboard: DashboardType | null, persistableDashboardFilters: DashboardFilter): DashboardFilterChange[] =>
                getDashboardFilterChanges(dashboard?.persisted_filters || {}, persistableDashboardFilters),
        ],
        changedFilterCount: [
            (s) => [s.filterChanges],
            (filterChanges: DashboardFilterChange[]): number => filterChanges.length,
        ],
        dashboardSettingsChanges: [
            (s) => [s.savedDashboardSettings, s.currentDashboardSettings, s.variables],
            (
                saved: DashboardSettings,
                current: DashboardSettings,
                variables: Variable[]
            ): DashboardSettingsChange[] => {
                const defaults = Object.fromEntries(
                    variables.map((variable) => [
                        variable.id,
                        {
                            code_name: variable.code_name,
                            variableId: variable.id,
                            value: variable.default_value,
                            isNull: variable.isNull,
                        },
                    ])
                )
                return [
                    ...getDashboardFilterChanges(saved.filters, current.filters),
                    ...getDashboardVariableChanges(saved.variables, current.variables, defaults),
                ]
            },
        ],
        // Does any tile on this dashboard reach past the team's events retention window? Runs the same date
        // precedence and the same rule the tiles do, so the banner and a tile's icon can't disagree.
        anyInsightExceedsRetention: [
            (s) => [s.insightTiles, s.effectiveEditBarFilters, s.retentionMonths],
            (
                insightTiles: DashboardTile[],
                dashboardFilters: DashboardFilter,
                retentionMonths: number | null
            ): boolean =>
                (insightTiles || []).some((tile) =>
                    exceedsRetention({
                        query: tile.insight?.query,
                        dateFromOverride: getEffectiveDateOverride(
                            tile.insight?.filter_override_context,
                            dashboardFilters,
                            tile.filters_overrides
                        ).dateFromOverride,
                        resolvedDateFrom: tile.insight?.resolved_date_range?.date_from,
                        retentionMonths,
                    })
                ),
        ],
        showRetentionBanner: [
            (s) => [s.warningEligible, s.anyInsightExceedsRetention, s.placement],
            (warningEligible: boolean, anyInsightExceedsRetention: boolean, placement: DashboardPlacement): boolean =>
                warningEligible &&
                anyInsightExceedsRetention &&
                // Shared and exported views have no upgrade path for the viewer, and a public viewer isn't our customer.
                placement !== DashboardPlacement.Public &&
                placement !== DashboardPlacement.Export,
        ],
        effectiveRefreshFilters: [
            (s) => [s.externalFilters, s.settingsForRefresh],
            (externalFilters: DashboardFilter, settings: DashboardSettings): DashboardFilter => {
                return combineDashboardFilters(settings.filters, externalFilters)
            },
        ],
        currentDashboardVariables: [
            (s) => [s.currentDashboardSettings],
            (settings: DashboardSettings) => settings.variables,
        ],
        hasUnsavedLayoutChanges: [
            (s) => [s.dashboard, s.savedTilePlacements, s.draftLayouts],
            (
                dashboard: DashboardType | null,
                savedTilePlacements: Record<DashboardTile['id'], TilePlacement>,
                draftLayouts: ResponsiveLayouts | null
            ): boolean => {
                if (!dashboard) {
                    return false
                }
                const draftByTile = draftLayouts ? layoutsByTile(draftLayouts) : null
                return (dashboard.tiles || []).some((tile: DashboardTile) => {
                    const saved = savedTilePlacements[tile.id]
                    const currentSm = draftByTile?.[tile.id]?.sm ?? tile.layouts?.sm
                    return !equal(saved?.layouts?.sm || {}, currentSm || {}) || tileGroupChanged(tile, saved)
                })
            },
        ],
        effectiveVariablesAndAssociatedInsights: [
            (s) => [s.dashboard, s.variables, s.currentDashboardVariables],
            (
                dashboard: DashboardType,
                variables: Variable[],
                dashboardVariables: Record<string, HogQLVariable>
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
                        if (!variable) {
                            return null
                        }

                        const dashboardVariable = dashboardVariables[v.variableId]
                        const variableSources = [dashboardVariable, v]
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
            (
                searchParams: Record<string, any>,
                variables: Variable[],
                initialVariablesLoaded: boolean
            ): Record<string, HogQLVariable> => {
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
            (
                effectiveVariablesAndAssociatedInsights: {
                    insightNames: string[]
                    variable: Variable
                }[]
            ) => Object.keys(effectiveVariablesAndAssociatedInsights).length > 0,
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
        readOnly: [() => [(_, props) => props.readOnly], (readOnly: boolean | undefined): boolean => !!readOnly],
        apiUrl: [
            (_, p) => [p.id],
            (id: number) => {
                return (
                    refresh?: RefreshType,
                    filtersOverride?: DashboardFilter,
                    variablesOverride?: Record<string, HogQLVariable>,
                    layoutSize?: 'sm' | 'xs'
                ) =>
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${id}/?${toParams({
                        refresh,
                        filters_override: filtersOverride,
                        variables_override: variablesOverride,
                        layout_size: layoutSize,
                    })}`
            },
        ],
        currentLayoutSize: [
            (s) => [s.containerWidth],
            (containerWidth: number | null): 'sm' | 'xs' => {
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
        tiles: [
            (s) => [s.dashboard],
            (dashboard: DashboardType | null) => dashboard?.tiles?.filter((t) => !t.deleted) || [],
        ],
        widgetTiles: [(s) => [s.tiles], (tiles: DashboardTile[]) => tiles.filter((t) => !!t.widget)],
        tileGroupSectionsEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean => !!featureFlags[FEATURE_FLAGS.DASHBOARD_TILE_GROUP_SECTIONS],
        ],
        collapsedTileGroupKeys: [
            (s) => [
                s.tileGroupSectionsEnabled,
                s.placement,
                s.tiles,
                s.dashboard,
                s.tileGroupChoices,
                s.revealedTileGroup,
            ],
            (
                tileGroupSectionsEnabled: boolean,
                placement: DashboardPlacement,
                tiles: DashboardTile[],
                dashboard: DashboardType | null,
                tileGroupChoices: TileGroupChoices,
                revealedTileGroup: RevealedTileGroup | null
            ): string[] =>
                // Exported images and subscription emails show every tile.
                tileGroupSectionsEnabled && dashboard && placement !== DashboardPlacement.Export
                    ? getCollapsedTileGroupKeys({
                          tiles,
                          groups: dashboard.customization?.groups,
                          choices: tileGroupChoices[dashboard.id],
                      }).filter((groupKey) => groupKey !== revealedTileGroup?.groupKey)
                    : [],
        ],
        collapsedTileIds: [
            (s) => [s.tiles, s.collapsedTileGroupKeys],
            (tiles: DashboardTile[], collapsedTileGroupKeys: string[]): Set<number> =>
                new Set(
                    tiles
                        .filter((tile) => tile.group_key && collapsedTileGroupKeys.includes(tile.group_key))
                        .map((tile) => tile.id)
                ),
        ],
        insightTiles: [
            (s) => [s.tiles],
            (tiles: DashboardTile[]) => tiles.filter((t) => !!t.insight).filter((i) => !i.insight?.deleted),
        ],
        textTiles: [(s) => [s.tiles], (tiles: DashboardTile[]) => tiles.filter((t) => !!t.text)],
        dashboardControlScopes: [
            (s) => [s.insightTiles],
            (insightTiles: DashboardTile[]): Record<DashboardControl, DashboardControlScope> =>
                getDashboardControlScopes(insightTiles),
        ],
        itemsLoading: [
            (s) => [s.dashboardLoading, s.dashboardStreaming, s.refreshStatus, s.initialVariablesLoaded],
            (
                dashboardLoading: boolean,
                dashboardStreaming: boolean,
                refreshStatus: Record<string, RefreshStatus>,
                initialVariablesLoaded: boolean
            ) => {
                return (
                    dashboardLoading ||
                    dashboardStreaming ||
                    Object.values(refreshStatus).some((s) => s.loading || s.queued) ||
                    (SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams && !initialVariablesLoaded)
                )
            },
        ],
        isRefreshingQueued: [
            (s) => [s.refreshStatus],
            (refreshStatus: Record<string, RefreshStatus>) => (id: string) => !!refreshStatus[id]?.queued,
        ],
        isRefreshing: [
            (s) => [s.refreshStatus],
            (refreshStatus: Record<string, RefreshStatus>) => (id: string) => !!refreshStatus[id]?.loading,
        ],
        highlightedInsightId: [
            () => [router.selectors.searchParams],
            (searchParams: Record<string, any>) => searchParams.highlightInsightId,
        ],
        // A refresh skips tiles in closed groups, so their age must not make the dashboard look stale:
        // on a shared dashboard that would force a full refresh on every load.
        sortedDates: [
            (s) => [s.insightTiles, s.collapsedTileIds],
            (insightTiles: DashboardTile[], collapsedTileIds: Set<number>): Dayjs[] => {
                if (!insightTiles || !insightTiles.length) {
                    return []
                }

                const validDates = insightTiles
                    .filter((tile) => !collapsedTileIds.has(tile.id))
                    .map((i) => dayjs(i.insight?.last_refresh))
                    .filter((date) => date.isValid())
                return sortDayJsDates(validDates)
            },
        ],
        oldestRefreshed: [
            // selecting page visibility to update the refresh when a page comes back into view
            (s) => [s.sortedDates, s.pageVisibility],
            (sortedDates: Dayjs[]): Dayjs | null => {
                if (!sortedDates.length) {
                    return null
                }

                return sortedDates[0]
            },
        ],
        effectiveLastRefresh: [
            (s) => [s.lastDashboardRefresh, s.oldestRefreshed],
            (lastDashboardRefresh: Dayjs | null, oldestRefreshed: Dayjs | null): Dayjs | null => {
                // Pessimistic: the banner must not claim the dashboard is fresher than the stalest insight
                // tile (per-tile menus use insight.last_refresh). `last_dashboard.last_refresh` and client
                // `updateDashboardLastRefresh(dayjs())` can otherwise run ahead of embedded tile metadata.
                return oldestRefreshed ?? lastDashboardRefresh ?? null
            },
        ],

        nextAllowedDashboardRefresh: [
            (s) => [s.lastDashboardRefresh],
            (lastDashboardRefresh: Dayjs | null): Dayjs | null => {
                if (!lastDashboardRefresh) {
                    return null
                }

                return lastDashboardRefresh.add(DASHBOARD_MIN_REFRESH_INTERVAL_MINUTES, 'minutes')
            },
        ],
        nextWidgetStaleAt: [
            (s) => [s.widgetTiles, s.widgetRefreshStatus],
            (
                widgetTiles: DashboardTile[],
                widgetRefreshStatus: Record<
                    number,
                    {
                        error?: string | null
                        fetchedAt?: number
                        loading?: boolean
                    }
                >
            ): number | null => {
                const deadlines = widgetTiles
                    .map((tile) => {
                        const status = widgetRefreshStatus[tile.id]
                        return status?.fetchedAt && !status.error && !status.loading
                            ? status.fetchedAt + WIDGET_CLIENT_TTL_MS
                            : null
                    })
                    .filter((deadline): deadline is number => deadline !== null && deadline > Date.now())
                return deadlines.length ? Math.min(...deadlines) : null
            },
        ],
        blockRefresh: [
            // page visibility is only here to trigger a recompute when the page is hidden/shown
            (s) => [
                s.nextAllowedDashboardRefresh,
                s.effectiveLastRefresh,
                s.widgetTiles,
                s.widgetRefreshStatus,
                s.refreshEligibilityTick,
                s.placement,
                s.collapsedTileIds,
                s.pageVisibility,
            ],
            (
                nextAllowedDashboardRefresh: Dayjs,
                effectiveLastRefresh: Dayjs | null,
                widgetTiles: DashboardTile[],
                widgetRefreshStatus: Record<number, { loading?: boolean; error?: string | null; fetchedAt?: number }>,
                _refreshEligibilityTick: number,
                placement: DashboardPlacement,
                collapsedTileIds: Set<number>
            ) => {
                return (
                    !(placement === DashboardPlacement.FeatureFlag) &&
                    !(placement === DashboardPlacement.Group) &&
                    !!nextAllowedDashboardRefresh &&
                    nextAllowedDashboardRefresh?.isAfter(now()) &&
                    !isEffectiveRefreshStale(effectiveLastRefresh) &&
                    !widgetTiles.some((tile) => {
                        const status = widgetRefreshStatus[tile.id]
                        return !collapsedTileIds.has(tile.id) && !status?.error && isWidgetStale(status)
                    })
                )
            },
        ],
        canEditDashboard: [
            (s) => [s.dashboard],
            (dashboard: DashboardType | null) => {
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
            (canEditDashboard: boolean, asDashboardTemplate: DashboardTemplateEditorType | undefined): boolean =>
                canEditDashboard && !!(asDashboardTemplate?.tiles?.length ?? 0),
        ],
        canRestrictDashboard: [
            // Sync conditions with backend can_user_restrict
            (s) => [s.dashboard, userLogic.selectors.user, teamLogic.selectors.currentTeam],
            (
                dashboard: DashboardType | null,
                user: null | import('~/types').UserType,
                currentTeam: null | import('~/types').TeamPublicType | import('~/types').TeamType
            ): boolean =>
                !!dashboard &&
                !!user &&
                (user.uuid === dashboard.created_by?.uuid ||
                    (!!currentTeam?.effective_membership_level &&
                        currentTeam.effective_membership_level >= OrganizationMembershipLevel.Admin)),
        ],
        sizeKey: [
            (s) => [s.columns],
            (columns: number | null): DashboardLayoutSize | undefined => {
                const [size] = (Object.entries(BREAKPOINT_COLUMN_COUNTS).find(([, value]) => value === columns) ||
                    []) as [DashboardLayoutSize, number]
                return size
            },
        ],
        layouts: [
            (s) => [s.tiles, s.draftLayouts],
            (tiles: DashboardTile[], draftLayouts: ResponsiveLayouts | null): ResponsiveLayouts =>
                calculateDraftLayouts(tiles, draftLayouts),
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
        /** Full-width bands, one per tile group, or none when the dashboard shows one grid. */
        tileGroupSections: [
            (s) => [s.tileGroupSectionsEnabled, s.tiles, s.layouts, s.dashboard, s.placement],
            (
                tileGroupSectionsEnabled: boolean,
                tiles: DashboardTile[],
                layouts: ResponsiveLayouts,
                dashboard: DashboardType | null,
                placement: DashboardPlacement
            ): DashboardSection[] => {
                if (!tileGroupSectionsEnabled || !tiles.some((tile) => tile.group_key)) {
                    return []
                }
                const widgetTilesShown = isWidgetTileVisibleOnPlacement(placement)
                return getDashboardSections({
                    tiles: tiles.filter((tile) => !tile.widget || widgetTilesShown),
                    layout: layouts.sm,
                    groups: dashboard?.customization?.groups,
                })
            },
        ],
        tileGroupSectionLayouts: [
            (s) => [s.tileGroupSections, s.layouts, s.dashboard],
            (
                tileGroupSections: DashboardSection[],
                layouts: ResponsiveLayouts,
                dashboard: DashboardType | null
            ): SectionLayouts[] => {
                const compactor = getDashboardGridCompactor(dashboard?.customization?.layout_compaction)
                return tileGroupSections.map((section) => getSectionLayouts(layouts, section.tiles, compactor))
            },
            { resultEqualityCheck: objectsEqual },
        ],
        tileGroupMoveOptions: [
            (s) => [s.tileGroupSections, s.canEditDashboard],
            (tileGroupSections: DashboardSection[], canEditDashboard: boolean): Record<number, TileGroupMoveOptions> =>
                canEditDashboard ? getTileGroupMoveOptions(tileGroupSections) : {},
            { resultEqualityCheck: objectsEqual },
        ],
        refreshMetrics: [
            (s) => [s.refreshStatus, s.refreshTilesTotal],
            (refreshStatus: Record<string, RefreshStatus>, refreshTilesTotal: number | null) => {
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
                dashboard: DashboardType | null,
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
            (id: number): ProjectTreeRef => {
                return { type: 'dashboard', ref: String(id) }
            },
        ],
        hasInvalidDashboardId: [
            () => [(_, props: DashboardLogicProps) => props.id],
            (id: number): boolean => !Number.isFinite(id),
        ],
        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.dashboard],
            (dashboard: DashboardType | null): SidePanelSceneContext | null => {
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
        dataColorThemeId: [
            (s) => [s.temporaryDataColorThemeId, s.dashboard],
            (
                temporaryDataColorThemeId: { themeId: number | null } | null,
                dashboard: DashboardType | null
            ): number | null =>
                temporaryDataColorThemeId
                    ? temporaryDataColorThemeId.themeId
                    : (dashboard?.data_color_theme_id ?? null),
        ],
        dataColorTheme: [
            (s) => [s.dataColorThemeId, s.getTheme],
            (
                dataColorThemeId: number | null,
                getTheme: (themeId: number | string | null | undefined) => DataColorTheme | null
            ): DataColorTheme | null => getTheme(dataColorThemeId),
        ],
        autoBreakdownColorsEnabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean =>
                !!featureFlags[FEATURE_FLAGS.PRODUCT_ANALYTICS_DASHBOARD_COLORS],
        ],
        // itemsLoading alone can't stand in for completeness: a refresh that errors or is
        // aborted before the insight ever got results leaves the tile with result: null after
        // loading settles, hiding its breakdown values from the sharing check.
        // A tile in a closed group still holds results from before the last refresh, so its values can be stale too.
        breakdownValuesIncomplete: [
            (s) => [s.itemsLoading, s.insightTiles, s.waitingTileRefresh],
            (
                itemsLoading: boolean,
                insightTiles: DashboardTile[] | null,
                waitingTileRefresh: WaitingTileRefresh | null
            ): boolean =>
                itemsLoading ||
                hasUnresolvedBreakdownTiles(insightTiles) ||
                !!insightTiles?.some((tile) => waitingTileRefresh?.tileIds.includes(tile.id)),
        ],
        // Persisted colors with unsaved edits merged over them, plus auto-assigned colors for
        // breakdown values shared by multiple tiles. This is both what tiles render and what a
        // save persists. Values unique to one tile keep position-based colors (see
        // computeTileFallbackTokens), so they don't consume palette slots here.
        effectiveBreakdownColors: [
            (s) => [
                s.temporaryBreakdownColors,
                s.dashboard,
                s.insightTiles,
                s.breakdownValuesIncomplete,
                s.autoBreakdownColorsEnabled,
                s.dataColorTheme,
            ],
            (
                temporaryBreakdownColors: BreakdownColorConfig[],
                dashboard: DashboardType | null,
                insightTiles: DashboardTile[] | null,
                breakdownValuesIncomplete: boolean,
                autoBreakdownColorsEnabled: boolean,
                dataColorTheme: DataColorTheme | null
            ): BreakdownColorConfig[] => {
                const merged = mergeBreakdownColorConfigs(
                    temporaryBreakdownColors,
                    dashboard?.breakdown_colors ?? []
                ).filter((config) => !!config.colorToken)

                if (!autoBreakdownColorsEnabled) {
                    return merged
                }

                const tileBreakdownValues = extractBreakdownValuesByTile(insightTiles)
                // Prune stale or no-longer-shared auto entries only when every tile's breakdown
                // values are known: with a partial tile set (still loading, or errored/aborted
                // without results) a genuinely shared value can look single-tile and would lose
                // its color.
                const isShared = buildSharedBreakdownValueLookup(tileBreakdownValues)
                const kept = breakdownValuesIncomplete
                    ? merged
                    : merged.filter((config) => config.source !== 'auto' || isShared(config))
                // Size assignment to the active theme — getColorFromToken wraps tokens past the
                // theme's color count, so assuming the default 15 slots on a smaller theme would
                // hand out visually duplicate colors while palette slots remain free.
                const paletteSize = dataColorTheme ? Object.keys(dataColorTheme).length : undefined
                return applyAutoBreakdownColors(tileBreakdownValues, kept, paletteSize)
            },
        ],
        hasUnsavedColorChanges: [
            (s) => [s.temporaryBreakdownColors, s.temporaryDataColorThemeId, s.dashboard],
            (
                temporaryBreakdownColors: BreakdownColorConfig[],
                temporaryDataColorThemeId: { themeId: number | null } | null,
                dashboard: DashboardType | null
            ): boolean => {
                const persisted = dashboard?.breakdown_colors ?? []
                const colorsChanged = temporaryBreakdownColors.some((config) => {
                    const persistedConfig = findBreakdownColorConfig(
                        persisted,
                        config.breakdownValue,
                        config.breakdownType,
                        config.breakdownProperty
                    )
                    return config.colorToken
                        ? persistedConfig?.colorToken !== config.colorToken
                        : !!persistedConfig?.colorToken
                })
                const themeChanged =
                    temporaryDataColorThemeId !== null &&
                    (temporaryDataColorThemeId.themeId ?? null) !== (dashboard?.data_color_theme_id ?? null)
                return colorsChanged || themeChanged
            },
        ],
        maxContext: [
            (s) => [s.dashboard],
            (dashboard: DashboardType | null): MaxContextInput[] => {
                if (!dashboard) {
                    return []
                }

                return [createMaxContextHelpers.dashboard(dashboard)]
            },
        ],
    })),
    subscriptions(({ actions, cache }) => ({
        nextAllowedDashboardRefresh: (deadline: Dayjs | null) => {
            cache.disposables.dispose('dashboardRefreshTimer')
            if (!deadline || !deadline.isAfter(now())) {
                return
            }
            cache.disposables.add(() => {
                const timerId = setTimeout(actions.recheckRefreshEligibility, Math.max(0, deadline.diff(now())) + 100)
                return () => clearTimeout(timerId)
            }, 'dashboardRefreshTimer')
        },
        nextWidgetStaleAt: (deadline: number | null) => {
            cache.disposables.dispose('widgetFreshnessTimer')
            if (!deadline) {
                return
            }
            cache.disposables.add(() => {
                const timerId = setTimeout(actions.recheckRefreshEligibility, Math.max(0, deadline - Date.now()) + 100)
                return () => clearTimeout(timerId)
            }, 'widgetFreshnessTimer')
        },
    })),
    events(({ actions, props, values, cache }) => ({
        afterMount: () => {
            // NOTE: initial dashboard load is done after variables are loaded in initialVariablesLoaded
            if (!Number.isFinite(props.id)) {
                actions.dashboardNotFound()
                return
            }
            // apiStatusLogic clears internetConnectionIssue only after a successful request, and a failed
            // dashboard sends no more requests. So the browser's online event must also start the retry.
            cache.disposables.add(
                () => {
                    const onOnline = (): void => {
                        if (cache.dashboardStreamActive) {
                            return
                        }
                        if (values.dashboardLoading || values.dashboardStreaming) {
                            cache.onlineRecoveryPending = true
                            return
                        }
                        if (values.dashboardFailedToLoad) {
                            actions.retryDashboardLoad()
                        }
                    }
                    window.addEventListener('online', onOnline)
                    return () => window.removeEventListener('online', onOnline)
                },
                'connectionRecoveryOnline',
                { pauseOnPageHidden: false }
            )
            if (props.id) {
                if (props.dashboard) {
                    // If we already have dashboard data, use it. Should the data turn out to be stale,
                    // the loadDashboardSuccess listener will initiate a refresh
                    // Ensure loading state is properly initialized for shared dashboards
                    actions.loadingDashboardItemsStarted(DashboardLoadAction.InitialLoad)
                    actions.loadDashboardSuccess(props.dashboard)
                } else {
                    const hasVariablesInUrl = SEARCH_PARAM_QUERY_VARIABLES_KEY in router.values.searchParams

                    if (!hasVariablesInUrl) {
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
                    // Deferred — variables wait for loadVariablesSuccess. Explicitly trigger
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
            cache.pendingFilterChange = undefined
            cache.widgetTileRefreshScheduler?.cancelAll()
            abortWidgetLoads(cache)
            abortGroupLoads(cache)
            actions.abortAnyRunningQuery()
        },
    })),
    sharedListeners(({ values, props, actions }) => ({
        reportRefreshTiming: ({ shortId }) => {
            const refreshStatus = values.refreshStatus[shortId]

            if (refreshStatus?.timer) {
                const loadingMilliseconds = new Date().getTime() - refreshStatus.timer.getTime()
                posthog.capture('insight refresh time', {
                    loadingMilliseconds: loadingMilliseconds,
                    insightShortId: shortId,
                })
            }
        },
        reportLoadTiming: () => {
            if (values.loadTimer) {
                const loadingMilliseconds = new Date().getTime() - values.loadTimer.getTime()
                posthog.capture('dashboard loading time', {
                    loadingMilliseconds: loadingMilliseconds,
                    dashboardId: props.id,
                })
            }
        },
        handleDashboardLoadComplete: () => {
            actions.revealHighlightedInsight()
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
        revealHighlightedInsight: () => {
            const insightId = values.highlightedInsightId
            const groupKey = values.tiles.find((tile) => insightId && tile.insight?.short_id === insightId)?.group_key
            if (!groupKey) {
                actions.setRevealedTileGroup(null)
            } else if (insightId !== values.revealedTileGroup?.insightId) {
                // Once per link, so a later URL change does not reopen a group the viewer closed.
                actions.setRevealedTileGroup({ insightId, groupKey })
                actions.refreshTileGroup(groupKey)
            }
        },
        updateTileGroupSectionLayout: ({ layouts }) => {
            const dashboardLayout = getLayoutAfterSectionChange(
                values.tileGroupSectionLayouts.map((sectionLayouts) => sectionLayouts.sm ?? []),
                layouts.sm ?? []
            )
            if (dashboardLayout) {
                actions.stageLayouts({ sm: dashboardLayout })
            }
        },
        moveTileToSection: async ({ tileId, sectionKey, cell, method }) => {
            const capture = ({ sourceGroupKey, groupKey }: TileMove): void => {
                if (sourceGroupKey !== groupKey) {
                    posthog.capture('dashboard tile moved between groups', {
                        dashboard_id: props.id,
                        from_group: sourceGroupKey !== null,
                        to_group: groupKey !== null,
                        method,
                    })
                }
            }
            if (values.layoutEditMode) {
                const move = planTileMove(values, tileId, sectionKey, cell)
                if (!move) {
                    return
                }
                actions.stageLayouts({ sm: move.layout })
                actions.setTileProperty(tileId, { group_key: move.groupKey })
                capture(move)
                if (move.groupKey && values.collapsedTileGroupKeys.includes(move.groupKey)) {
                    lemonToast.info(move.message)
                }
                return
            }
            await enqueueTileSave({ cache, mount: (): (() => void) => dashboardLogic(props).mount() }, async () => {
                const move = planTileMove(values, tileId, sectionKey, cell)
                if (!move) {
                    return
                }
                const { sm, placement } = placementAfterMove(move, tileId)
                const savedBefore = savedTilePlacement(values.savedTilePlacements, tileId)
                actions.setTileProperty(tileId, placement)
                const currentPlacement = (): TilePlacement | null => {
                    const tile = values.tiles.find((candidate) => candidate.id === tileId)
                    return tile ? tilePlacement(tile) : null
                }
                try {
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                    await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                        tiles: [{ id: tileId, ...placement }],
                    })
                    actions.tilePlacementsSaved({ [tileId]: placement })
                    // A discard while the request was out put the tile back, but an edit staged since then is newer.
                    if (values.draftLayouts === null && equal(currentPlacement(), savedBefore)) {
                        actions.setTileProperty(tileId, placement)
                    }
                    capture(move)
                    lemonToast.success(move.message)
                } catch {
                    lemonToast.error('Could not move the tile, so it is back where it was. Try again.')
                    // A move of this tile in edit mode is newer than this one, so it stays.
                    if (equal(currentPlacement(), placement)) {
                        const saved = savedTilePlacement(values.savedTilePlacements, tileId)
                        actions.setTileProperty(tileId, saved)
                        // A layout staged in edit mode since the move holds the moved cell, so it goes back too.
                        const draft = values.draftLayouts
                        if (draft?.sm && sm) {
                            const draftSm = withStagedCellReverted(draft.sm, tileId, sm, saved.layouts?.sm)
                            if (draftSm !== draft.sm) {
                                actions.stageLayouts({ ...draft, sm: draftSm })
                            }
                        }
                    }
                }
            })
        },
        [dashboardsModel.actionTypes.updateDashboardSuccess]: ({
            dashboard,
            payload,
        }: {
            dashboard: DashboardType | null
            payload?: { layoutsPersisted?: boolean }
        }) => {
            if (!dashboard || !values.dashboard || dashboard.id !== props.id || values.dashboard.id !== dashboard.id) {
                return
            }

            const layoutsPersisted = payload?.layoutsPersisted === true
            const previousTiles = new Map(values.dashboard.tiles.map((tile) => [tile.id, tile]))
            const savedBefore = values.savedTilePlacements
            const originalLayouts = layoutsPersisted
                ? layoutsByTile(
                      calculateLayouts(
                          values.dashboard.tiles.map((tile) => withTilePlacement(tile, savedBefore[tile.id]))
                      )
                  )
                : null
            const savedPlacements = Object.fromEntries(
                dashboard.tiles.map((tile) => [
                    tile.id,
                    !layoutsPersisted && previousTiles.has(tile.id)
                        ? (savedBefore[tile.id] ?? tilePlacement(tile))
                        : tilePlacement(tile),
                ])
            )
            const tiles = dashboard.tiles.map((tile) => {
                const previousTile = previousTiles.get(tile.id)
                if (!previousTile) {
                    return tile
                }
                if (!layoutsPersisted) {
                    return withTilePlacement(tile, tilePlacement(previousTile))
                }
                const draftSm = previousTile.layouts?.sm
                const originalSm = originalLayouts?.[tile.id]?.sm
                const layoutMoved = !!draftSm && !!originalSm && !sameGridCell(draftSm, originalSm)
                const groupMoved = tileGroupChanged(previousTile, savedBefore[tile.id])
                return withTilePlacement(tile, {
                    layouts: layoutMoved ? previousTile.layouts : tile.layouts,
                    group_key: groupMoved ? (previousTile.group_key ?? null) : (tile.group_key ?? null),
                })
            })

            actions.applyDashboardUpdate({ ...dashboard, tiles }, savedPlacements)
        },
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
                // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
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
                // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
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
            if (cache.onlineRecoveryPending || (cache.connectionRecoveryPending && !values.internetConnectionIssue)) {
                cache.onlineRecoveryPending = false
                cache.connectionRecoveryPending = false
                actions.retryDashboardLoad()
            }
        },
        setDashboardStreamFailed: () => {
            if (cache.dashboardStreamActive) {
                return
            }
            if (cache.onlineRecoveryPending || (cache.connectionRecoveryPending && !values.internetConnectionIssue)) {
                cache.onlineRecoveryPending = false
                cache.connectionRecoveryPending = false
                actions.retryDashboardLoad()
            }
        },
        retryDashboardLoad: () => {
            if (values.shouldUseStreaming) {
                actions.loadDashboardStreaming({ action: DashboardLoadAction.InitialLoad, retry: true })
            } else {
                actions.loadDashboard({ action: DashboardLoadAction.InitialLoad })
            }
        },
        [apiStatusLogic.actionTypes.setInternetConnectionIssue]: ({ issue }: { issue: boolean }) => {
            cache.connectionRecoveryPending = false
            if (issue || cache.dashboardStreamActive) {
                return
            }
            if (values.dashboardLoading || values.dashboardStreaming) {
                // The connection came back during a load. If that load fails, retry it once.
                cache.connectionRecoveryPending = true
                return
            }
            if (values.dashboardFailedToLoad) {
                actions.retryDashboardLoad()
            }
        },
        tileStreamingFailure: ({ error, willRetry }) => {
            // Only a genuine 404 response means the dashboard is missing. Stream errors can contain
            // "404" in their message even when the dashboard still exists.
            if (error?.status === 404) {
                actions.dashboardNotFound()
            } else if (isAccessDeniedError(error)) {
                actions.setAccessDeniedToDashboard()
            } else {
                // Show error toast for other errors (500s, network issues, etc.)
                const errorMessage = error?.message || 'Dashboard streaming failed'
                lemonToast.error(`Failed to load dashboard: ${errorMessage}`)
                // A stopped stream can leave missing tiles even after metadata arrived. Keep recovery
                // available for terminal errors, and show a load error when there is nothing to render.
                if (!willRetry || !values.dashboard) {
                    actions.setDashboardStreamFailed()
                }
            }
        },

        [insightsModel.actionTypes.insightSaved]: ({ shortId }: { shortId: InsightShortId }) => {
            for (const tile of values.insightTiles) {
                if (tile.insight?.short_id === shortId) {
                    actions.refreshDashboardItem({ tile })
                }
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
        [dashboardsModel.actionTypes.updateDashboardInsight]: ({
            insight,
            extraDashboardIds,
            sourceDashboardId,
        }: {
            insight: InsightModel
            extraDashboardIds?: number[]
            sourceDashboardId?: number
        }) => {
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
        [insightsModel.actionTypes.renameInsightSuccess]: ({ item }: { item: InsightModel }) => {
            const targetDashboards = (item.dashboard_tiles || []).map((tile) => tile.dashboard_id)
            if (!targetDashboards.includes(props.id)) {
                // this update is not for this dashboard
                return
            }

            const tileIndex = values.tiles.findIndex((t) => !!t.insight && t.insight.short_id === item.short_id)

            if (tileIndex === -1) {
                // the rename landed before this dashboard had the tile in state, so the reducer
                // could not patch it and the tile would show the stale name forever - reload instead
                actions.loadDashboard({ action: DashboardLoadAction.Update })
            }
        },
        duplicateTile: () => {
            cache.widgetTileIdsBeforeDuplicate = new Set(values.widgetTiles.map((tile) => tile.id))
        },
        duplicateTileSuccess: ({ dashboard }) => {
            if (!dashboard) {
                return
            }

            if (values.draftLayouts) {
                actions.stageLayouts(
                    calculateDraftLayouts(
                        dashboard.tiles.filter((tile) => !tile.deleted),
                        values.draftLayouts,
                        values.savedTilePlacements
                    )
                )
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
            const tile = cache.removedTileForUndo as DashboardTile | undefined
            cache.removedTileForUndo = undefined
            if (!tile) {
                return
            }

            const tileName = getDashboardTileDisplayName(tile)
            const isWidgetTile = !!tile.widget
            const removedMessage = isWidgetTile ? 'widget removed' : 'has been removed from the dashboard'
            const toastId = `remove-tile-${tile.id}`
            const otherDashboardIds = new Set(
                liveDashboardIds(tile.insight?.dashboard_tiles).filter((dashboardId) => dashboardId !== props.id)
            )
            const canDeleteInsight =
                tile.insight?.user_access_level !== AccessControlLevel.Viewer &&
                (!tile.insight?.user_access_level ||
                    accessLevelSatisfied(
                        AccessControlResourceType.Insight,
                        tile.insight.user_access_level,
                        AccessControlLevel.Editor
                    ))
            const deleteInsight = (): void => {
                const insight = tile.insight
                if (!insight) {
                    return
                }

                const otherDashboards = Array.from(otherDashboardIds).map((dashboardId) => ({
                    id: dashboardId,
                    name: dashboardsModel.values.rawDashboards[dashboardId]?.name || `Dashboard ${dashboardId}`,
                }))
                const dashboardIds = [props.id, ...otherDashboardIds]
                const otherDashboardCount = otherDashboards.length

                LemonDialog.open({
                    title: 'Delete insight everywhere?',
                    shouldAwaitSubmit: true,
                    description: (
                        <div className="pt-2 space-y-4">
                            {otherDashboards.length > 0 && (
                                <div>
                                    <div>This insight is also used on:</div>
                                    <ul className="list-inside list-disc">
                                        {otherDashboards.map((dashboard) => (
                                            <li key={dashboard.id}>
                                                <Link to={urls.dashboard(dashboard.id)}>{dashboard.name}</Link>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            )}
                            <div>
                                This deletes the insight and removes it from every dashboard. You can undo this action.
                            </div>
                        </div>
                    ),
                    primaryButton: {
                        children: 'Delete insight everywhere',
                        status: 'danger',
                        onClick: () => {
                            posthog.capture('dashboard insight delete after removal confirmed', {
                                other_dashboard_count: otherDashboardCount,
                            })
                            return deleteInsightWithUndo({
                                object: { ...insight, dashboards: dashboardIds },
                                endpoint: `projects/${values.currentTeamId}/insights`,
                                callback: (undo) => {
                                    const updatedInsight = {
                                        ...insight,
                                        deleted: !undo,
                                        dashboard_tiles: undo ? insight.dashboard_tiles : [],
                                    }
                                    dashboardsModel.actions.updateDashboardInsight(updatedInsight, dashboardIds)
                                    if (!undo) {
                                        lemonToast.dismiss(toastId)
                                    }
                                },
                            })
                        },
                    },
                    secondaryButton: { children: 'Cancel' },
                })
            }
            const undoTileRemoval = async (): Promise<void> => {
                try {
                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                    await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                        tiles: [{ id: tile.id, deleted: false }],
                    })

                    if (tile.insight) {
                        const insight = tile.insight
                        const nextDashboardTiles = liveDashboardIds(insight.dashboard_tiles).includes(props.id)
                            ? insight.dashboard_tiles
                            : [...(insight.dashboard_tiles || []), { id: tile.id, dashboard_id: props.id }]
                        dashboardsModel.actions.updateDashboardInsight(
                            { ...insight, dashboard_tiles: nextDashboardTiles },
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
            }

            lemonToast.info(
                tile.insight ? (
                    <span className="flex flex-col gap-2">
                        <span>
                            <b>{tileName}</b> {removedMessage}
                        </span>
                        <span className="flex items-center gap-2">
                            {canDeleteInsight && (
                                <LemonButton
                                    type="primary"
                                    status="danger"
                                    size="small"
                                    data-attr="delete-removed-insight"
                                    className="!m-0"
                                    onClick={() => {
                                        eventUsageLogic.actions.reportDashboardInsightDeleteAfterRemovalClicked(
                                            otherDashboardIds.size
                                        )
                                        deleteInsight()
                                    }}
                                >
                                    Delete insight everywhere
                                </LemonButton>
                            )}
                            <LemonButton
                                type="secondary"
                                size="small"
                                data-attr="undo-remove-tile-from-dashboard"
                                className="!m-0"
                                onClick={() => {
                                    void undoTileRemoval()
                                    lemonToast.dismiss(toastId)
                                }}
                            >
                                Undo
                            </LemonButton>
                        </span>
                    </span>
                ) : (
                    <>
                        <b>{tileName}</b> {removedMessage}
                    </>
                ),
                tile.insight
                    ? { toastId }
                    : {
                          toastId,
                          button: {
                              label: 'Undo',
                              dataAttr: 'undo-remove-tile-from-dashboard',
                              action: undoTileRemoval,
                          },
                      }
            )
        },
        moveToDashboardSuccess: ({ payload }) => {
            if (payload?.toDashboard === undefined || payload?.tile === undefined) {
                return
            }

            const { tile, fromDashboard, toDashboard, toDashboardName } = payload
            const updatedTile: DashboardTile = { ...tile }

            const nextTilePlacement = (
                existing: DashboardTileBasicType[] | null | undefined
            ): DashboardTileBasicType[] => [
                ...(existing || []).filter((t) => t.dashboard_id !== fromDashboard),
                { id: tile.id, dashboard_id: toDashboard },
            ]

            if (updatedTile.insight) {
                const ins = updatedTile.insight
                updatedTile.insight = {
                    ...ins,
                    dashboard_tiles: nextTilePlacement(ins.dashboard_tiles ?? undefined),
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
        saveDashboardTileSpacing: async ({ tileSpacing }, breakpoint) => {
            await breakpoint(750)

            if (cache.dashboardTileSpacingSaveInFlight) {
                cache.pendingDashboardTileSpacing = tileSpacing
                return
            }

            const persistedDashboard = dashboardsModel.values.rawDashboards[props.id]
            const persistedTileSpacing =
                persistedDashboard && 'customization' in persistedDashboard
                    ? (persistedDashboard.customization?.tile_spacing ?? 'standard')
                    : 'standard'
            cache.dashboardTileSpacingSaveInFlight = true
            actions.setDashboardTileSpacingSaving(true)
            try {
                // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                const dashboard = await api.update<DashboardType>(
                    `api/projects/${values.currentTeamId}/dashboards/${props.id}`,
                    {
                        grid_spacing: tileSpacing,
                        layout_compaction:
                            values.dashboard?.customization?.layout_compaction ?? DashboardGridCompaction.Vertical,
                    }
                )
                dashboardsModel.actions.updateDashboardSuccess(dashboard, {
                    layoutsPersisted: true,
                })
                eventUsageLogic.actions.reportDashboardTileDensityConfigured(tileSpacing)
            } catch {
                if (!cache.pendingDashboardTileSpacing) {
                    actions.setDashboardTileSpacing(persistedTileSpacing)
                    actions.loadDashboard({ action: DashboardLoadAction.Update })
                    lemonToast.error("Couldn't update tile density. Try again.")
                }
            } finally {
                cache.dashboardTileSpacingSaveInFlight = false
                const pendingTileSpacing = cache.pendingDashboardTileSpacing as DashboardTileSpacing | undefined
                cache.pendingDashboardTileSpacing = undefined
                if (pendingTileSpacing) {
                    actions.setDashboardTileSpacing(pendingTileSpacing)
                    actions.saveDashboardTileSpacing(pendingTileSpacing)
                } else {
                    actions.setDashboardTileSpacingSaving(false)
                }
            }
        },
        saveDashboardGridCompaction: async ({ layoutCompaction }, breakpoint) => {
            await breakpoint(750)

            if (cache.dashboardGridCompactionSaveInFlight) {
                cache.pendingDashboardGridCompaction = layoutCompaction
                return
            }

            const persistedDashboard = dashboardsModel.values.rawDashboards[props.id]
            const persistedLayoutCompaction =
                persistedDashboard && 'customization' in persistedDashboard
                    ? (persistedDashboard.customization?.layout_compaction ?? DashboardGridCompaction.Vertical)
                    : DashboardGridCompaction.Vertical
            cache.dashboardGridCompactionSaveInFlight = true
            try {
                // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                const dashboard = await api.update<DashboardType>(
                    `api/projects/${values.currentTeamId}/dashboards/${props.id}`,
                    {
                        layout_compaction: layoutCompaction,
                        grid_spacing: values.dashboard?.customization?.tile_spacing ?? 'standard',
                    }
                )
                dashboardsModel.actions.updateDashboardSuccess(dashboard, {
                    layoutsPersisted: true,
                })
            } catch (error) {
                posthog.captureException(error)
                if (!cache.pendingDashboardGridCompaction) {
                    actions.setDashboardGridCompaction(persistedLayoutCompaction)
                    actions.loadDashboard({ action: DashboardLoadAction.Update })
                }
                lemonToast.error("Couldn't update tile movement. Try again.")
            } finally {
                cache.dashboardGridCompactionSaveInFlight = false
                const pendingLayoutCompaction = cache.pendingDashboardGridCompaction as
                    | DashboardGridCompaction
                    | undefined
                cache.pendingDashboardGridCompaction = undefined
                if (pendingLayoutCompaction) {
                    actions.setDashboardGridCompaction(pendingLayoutCompaction)
                    actions.saveDashboardGridCompaction(pendingLayoutCompaction)
                }
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
            // The refresh loads every open widget again, and an older load must not land over the new one.
            abortWidgetLoads(cache)
            actions.resetInterval()
            actions.refreshDashboardItems({ action: RefreshDashboardItemsAction.Refresh, forceRefresh: true })
            if (values.placement !== DashboardPlacement.Export && values.placement !== DashboardPlacement.Public) {
                const widgetTileIds = values.widgetTiles
                    .filter((tile) => !values.collapsedTileIds.has(tile.id))
                    .map((tile) => tile.id)
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
            const { currentTeamId, effectiveRefreshFilters, settingsForRefresh, urlFilters } = values
            const savedMetricVariables = values.savedDashboardSettings.filters.metricVariables ?? []
            const urlVariables = settingsForRefresh.variables
            const pendingFilterChange: PendingFilterChange | undefined = cache.pendingFilterChange
            const filterChange =
                pendingFilterChange && dashboardSettingsMatch(pendingFilterChange.settings, settingsForRefresh)
                    ? pendingFilterChange
                    : undefined
            filterChange?.remainingInsightIds.add(insight.short_id)

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
                    withCompactMetricVariables(effectiveRefreshFilters, savedMetricVariables),
                    urlVariables,
                    tile.filters_overrides
                )

                const queryError = refreshedInsight ? getInsightQueryError(refreshedInsight) : null
                const succeeded = !!refreshedInsight && !isRefreshRejectionStub(refreshedInsight) && !queryError
                if (succeeded) {
                    dashboardsModel.actions.updateDashboardInsight(refreshedInsight, undefined, dashboardId)
                    actions.setRefreshStatus(insight.short_id)
                } else {
                    actions.setRefreshError(insight.short_id, queryError?.code ? queryError : undefined)
                }
                const currentFilterChange =
                    filterChange &&
                    cache.pendingFilterChange?.id === filterChange.id &&
                    dashboardSettingsMatch(settingsForRefresh, values.currentDashboardSettings)
                        ? filterChange
                        : undefined
                if (currentFilterChange) {
                    if (succeeded) {
                        currentFilterChange.remainingInsightIds.delete(insight.short_id)
                    } else {
                        currentFilterChange.remainingInsightIds.add(insight.short_id)
                    }
                }
                reportDashboardTileRefreshed(
                    dashboardId,
                    tile,
                    urlFilters,
                    urlVariables,
                    Math.floor(performance.now() - refreshStartTime),
                    true,
                    currentFilterChange
                )
                if (currentFilterChange?.remainingInsightIds.size === 0) {
                    cache.pendingFilterChange = undefined
                }
            } catch (e: any) {
                actions.setRefreshError(insight.short_id, e)
            }
        },
        refreshDashboardItems: async ({ action, forceRefresh, previewUnsavedFilters }, breakpoint) => {
            cache.disposables.dispose('openGroupReload')
            abortGroupLoads(cache)
            const groupSignal = (cache.groupAbortController = new AbortController()).signal
            const dashboardRefreshStartTime = performance.now()
            const settingsToRefresh = previewUnsavedFilters
                ? values.currentDashboardSettings
                : values.settingsForRefresh
            const pendingFilterChange: PendingFilterChange | undefined = cache.pendingFilterChange
            const filterChange =
                pendingFilterChange && dashboardSettingsMatch(pendingFilterChange.settings, settingsToRefresh)
                    ? pendingFilterChange
                    : undefined
            const isInitialLoad =
                action === DashboardLoadAction.InitialLoad || action === DashboardLoadAction.InitialLoadWithVariables
            const isInitialLoadOrUpdate = isInitialLoad || action === DashboardLoadAction.Update
            const initialUrlOverridesArePreviewed =
                isInitialLoad && !values.canAutoPreview && values.dashboardSettingsState === 'unsavedChanges'

            const dashboardId: number = props.id
            const { collapsedTileIds } = values
            const allInsightTiles = values.insightTiles || []
            const totalTileCount = allInsightTiles.length
            if (filterChange) {
                filterChange.remainingInsightIds = new Set(
                    allInsightTiles
                        .filter((tile) => !collapsedTileIds.has(tile.id))
                        .map((tile) => tile.insight!.short_id)
                )
            }

            const staleTiles = allInsightTiles
                // sort tiles so we poll them in the exact order they are computed on the backend
                .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
                .filter((t): t is DashboardTile & { insight: InsightModel } => !!t.insight)
                // only refresh stale insights
                .filter(
                    (t) =>
                        forceRefresh ||
                        !isInitialLoadOrUpdate ||
                        !t.insight.cache_target_age ||
                        dayjs(t.insight.cache_target_age).isBefore(dayjs())
                )
            const sortedTilesToRefresh = staleTiles.filter((tile) => !collapsedTileIds.has(tile.id))
            const widgetTileIds = values.widgetTiles.map((tile) => tile.id)
            const openWidgetTileIds = widgetTileIds.filter((id) => !collapsedTileIds.has(id))
            const waiting = nextWaitingTileRefresh({
                previous: values.waitingTileRefresh,
                tiles: values.tiles,
                collapsedTileIds,
                candidateTileIds: [...staleTiles.map((tile) => tile.id), ...widgetTileIds],
                forceRefresh: !!forceRefresh,
                settings: settingsToRefresh,
            })
            actions.setWaitingTileRefresh(waiting)

            const tilesStaleCount = sortedTilesToRefresh.length
            let tilesRefreshedCount = 0
            let tilesRefreshedCachedCount = 0
            let tilesErroredCount = 0
            let tilesAbortedCount = 0

            if (sortedTilesToRefresh.length > 0) {
                // Mark tiles as queued before the breakpoint's await, so there's no render gap
                // between the refreshDashboardItems reducer wiping refreshStatus to {} and it
                // being repopulated - otherwise tiles briefly show as "not queued" and fall
                // through to the query's default empty state instead of the loading state.
                actions.setRefreshTilesTotal(tilesStaleCount)
                actions.setRefreshStatuses(
                    sortedTilesToRefresh.map((tile) => tile.insight.short_id),
                    false,
                    true
                )

                await breakpoint()

                actions.abortAnyRunningQuery()
                cache.abortController = new AbortController()
            }

            const openGroupsWaiting = (): Set<string> =>
                openTileGroupsWaiting(values.tiles, values.collapsedTileIds, values.waitingTileRefresh)
            if (openGroupsWaiting().size > 0) {
                // The aborted group load clears its queued status a few microtasks later, and that status blocks a reload.
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        if (!groupSignal.aborted) {
                            openGroupsWaiting().forEach((groupKey) => actions.refreshTileGroup(groupKey))
                        }
                    }, 0)
                    return () => clearTimeout(timerId)
                }, 'openGroupReload')
            }

            if (sortedTilesToRefresh.length > 0) {
                // Cache values used during and after the long-running fetch, since the logic
                // may be unmounted by the time the awaits complete (kea's no-arg breakpoint()
                // only cancels on newer invocations, not on unmount).
                const { currentTeamId, externalFilters, urlFilters, dashboardLoadData, lastDashboardRefresh } = values
                const effectiveRefreshFilters = combineDashboardFilters(settingsToRefresh.filters, externalFilters)
                const savedMetricVariables = values.savedDashboardSettings.filters.metricVariables ?? []
                const urlVariables = settingsToRefresh.variables

                const tileRefresh: InsightTileRefresh = {
                    actions,
                    dashboardId,
                    currentTeamId,
                    filters: withCompactMetricVariables(effectiveRefreshFilters, savedMetricVariables),
                    variables: urlVariables,
                    urlFilters,
                    forceRefresh: !!forceRefresh,
                    signal: cache.abortController.signal,
                    queue: tileLoadQueue(cache),
                }
                const loadingHere = (cache.refreshingTileIds = new Set(sortedTilesToRefresh.map((tile) => tile.id)))
                const fetchSyncInsightFunctions = sortedTilesToRefresh.map((tile) => async () => {
                    const outcome = await refreshInsightTile(tile, tileRefresh)
                    loadingHere.delete(tile.id)
                    if (outcome === 'refreshed' || outcome === 'cached') {
                        if (waiting.tileIds.includes(tile.id)) {
                            actions.clearWaitingTileRefresh([tile.id])
                        }
                        tilesRefreshedCount++
                        tilesRefreshedCachedCount += outcome === 'cached' ? 1 : 0
                        filterChange?.remainingInsightIds.delete(tile.insight.short_id)
                    } else {
                        filterChange?.remainingInsightIds.add(tile.insight.short_id)
                        tilesAbortedCount += outcome === 'aborted' ? 1 : 0
                        tilesErroredCount += outcome === 'errored' ? 1 : 0
                    }
                })

                await Promise.all(fetchSyncInsightFunctions.map((fetchInsight) => fetchInsight()))
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

                const refreshDurationMs = Math.floor(performance.now() - dashboardRefreshStartTime)
                const filterChangeIsCurrent =
                    filterChange &&
                    cache.pendingFilterChange?.id === filterChange.id &&
                    dashboardSettingsMatch(settingsToRefresh, values.currentDashboardSettings)
                const allInsightsSucceeded = filterChangeIsCurrent
                    ? filterChange.remainingInsightIds.size === 0
                    : tilesRefreshedCount === totalTileCount && tilesErroredCount === 0 && tilesAbortedCount === 0
                posthog.capture(`dashboard refreshed`, {
                    dashboard_id: dashboardId,
                    filters: filtersForAnalytics(urlFilters),
                    variables: urlVariables,
                    last_refreshed: lastDashboardRefresh?.toString(),
                    refreshAge: lastDashboardRefresh ? now().diff(lastDashboardRefresh, 'seconds') : undefined,
                    action: action,
                    force_refresh: !!forceRefresh,
                    refresh_duration_ms: refreshDurationMs,
                    total_tile_count: totalTileCount,
                    tiles_stale_count: tilesStaleCount,
                    tiles_deferred_count: staleTiles.length - tilesStaleCount,
                    tiles_refreshed_count: tilesRefreshedCount,
                    tiles_errored_count: tilesErroredCount,
                    tiles_aborted_count: tilesAbortedCount,
                    ...(filterChangeIsCurrent
                        ? {
                              filter_change_id: filterChange.id,
                              filter_change_duration_ms: Math.floor(performance.now() - filterChange.startTime),
                              all_insights_succeeded: allInsightsSucceeded,
                          }
                        : {}),
                })
                if (filterChangeIsCurrent && allInsightsSucceeded) {
                    cache.pendingFilterChange = undefined
                }
            }

            // Also when every insight sits in a closed group, so the preview settles and later refreshes use it.
            if (
                (previewUnsavedFilters || initialUrlOverridesArePreviewed) &&
                (tilesErroredCount > 0 || tilesAbortedCount > 0)
            ) {
                actions.previewDashboardChangesFailure()
            } else if (previewUnsavedFilters || initialUrlOverridesArePreviewed) {
                actions.setPreviewedDashboardSettings(settingsToRefresh)
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

            if (openWidgetTileIds.length > 0) {
                actions.refreshDashboardWidgets({ tileIds: openWidgetTileIds, forceRefresh: !!forceRefresh })
            }
        },
        toggleTileGroup: ({ groupKey }) => {
            const collapse = !values.collapsedTileGroupKeys.includes(groupKey)
            posthog.capture('dashboard tile group toggled', {
                dashboard_id: props.id,
                collapsed: collapse,
                tile_count: values.tiles.filter((tile) => tile.group_key === groupKey).length,
            })
            dashboardTileGroupChoicesLogic.actions.setTileGroupCollapsed(props.id, groupKey, collapse)
            if (!collapse) {
                actions.refreshTileGroup(groupKey)
            }
        },
        refreshTileGroup: async ({ groupKey }) => {
            const { waitingTileRefresh: waiting, refreshStatus, widgetRefreshStatus } = values
            // A tile leaves the waiting list only once it loads, so one still loading must not load again.
            const tiles = values.tiles.filter(
                (tile) =>
                    tile.group_key === groupKey &&
                    waiting?.tileIds.includes(tile.id) &&
                    !cache.refreshingTileIds?.has(tile.id) &&
                    !(tile.insight
                        ? refreshStatus[tile.insight.short_id]?.queued
                        : widgetRefreshStatus[tile.id]?.loading)
            )
            if (!waiting || tiles.length === 0) {
                return
            }

            const widgetTileIds = tiles.filter((tile) => tile.widget).map((tile) => tile.id)
            if (widgetTileIds.length > 0) {
                actions.refreshDashboardWidgets({ tileIds: widgetTileIds, forceRefresh: waiting.forceRefresh })
            }

            const insightTiles = tiles.filter(
                (tile): tile is DashboardTile & { insight: InsightModel } => !!tile.insight
            )
            if (insightTiles.length === 0) {
                return
            }
            // Grow "X out of Y", so the tiles that already loaded still count as done.
            actions.setRefreshTilesTotal(
                (values.refreshTilesTotal ?? Object.keys(refreshStatus).length) +
                    insightTiles.filter((tile) => !(tile.insight.short_id in refreshStatus)).length
            )
            insightTiles.forEach((tile) => actions.setRefreshStatus(tile.insight.short_id, false, true))

            cache.groupAbortController ??= new AbortController()
            const tileRefresh: InsightTileRefresh = {
                actions,
                dashboardId: props.id,
                currentTeamId: values.currentTeamId,
                filters: withCompactMetricVariables(
                    combineDashboardFilters(waiting.settings.filters, values.externalFilters),
                    values.savedDashboardSettings.filters.metricVariables ?? []
                ),
                variables: waiting.settings.variables,
                urlFilters: values.urlFilters,
                forceRefresh: waiting.forceRefresh,
                signal: cache.groupAbortController.signal,
                queue: tileLoadQueue(cache),
            }
            await Promise.all(
                insightTiles.map(async (tile) => {
                    const outcome = await refreshInsightTile(tile, tileRefresh)
                    if (outcome === 'refreshed' || outcome === 'cached') {
                        actions.clearWaitingTileRefresh([tile.id])
                    }
                })
            )
        },
        refreshDashboardWidgets: async ({ tileIds, forceRefresh }, breakpoint) => {
            if (values.placement === DashboardPlacement.Export || values.placement === DashboardPlacement.Public) {
                return
            }

            const loadingTileIds = forceRefresh
                ? []
                : tileIds.filter((tileId) => values.widgetRefreshStatus[tileId]?.loading)
            const staleTileIds = tileIds.filter((tileId) => {
                if (forceRefresh) {
                    return true
                }
                const fetchedAt = values.widgetRefreshStatus[tileId]?.fetchedAt
                return (
                    !loadingTileIds.includes(tileId) &&
                    (!!values.widgetRefreshStatus[tileId]?.error ||
                        !fetchedAt ||
                        Date.now() - fetchedAt >= WIDGET_CLIENT_TTL_MS)
                )
            })

            actions.clearWaitingTileRefresh(
                tileIds.filter((tileId) => !staleTileIds.includes(tileId) && !loadingTileIds.includes(tileId))
            )
            if (staleTileIds.length === 0) {
                return
            }

            // Not the insight queries' controller: every insight refresh aborts that one, and an aborted widget load
            // would show an error rather than its results. Only a cancel or a manual refresh stops widget loads.
            cache.widgetAbortController ??= new AbortController()
            const { signal } = cache.widgetAbortController
            cache.widgetLoadSignals ??= new Map<number, AbortSignal>()
            staleTileIds.forEach((tileId) => cache.widgetLoadSignals.set(tileId, signal))
            actions.setWidgetRefreshStatuses(staleTileIds, true)
            await breakpoint()

            const projectId = String(values.currentTeamId)
            const dashboardId = props.id
            const queue = tileLoadQueue(cache)
            const fetchFunctions = chunkTileIds(staleTileIds, 4).map((chunk) => async () => {
                try {
                    const results = await queue.run(
                        () => fetchRunWidgets(projectId, dashboardId, chunk, { signal }),
                        signal
                    )
                    const resultsByTileId = Object.fromEntries(results.map((result) => [result.tile_id, result]))
                    actions.setWidgetRunResults(resultsByTileId)
                    actions.clearWaitingTileRefresh(results.filter((result) => !result.error).map((r) => r.tile_id))
                    for (const result of results) {
                        actions.setWidgetRefreshStatuses(
                            [result.tile_id],
                            false,
                            result.error ? DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE : null
                        )
                    }
                } catch {
                    if (signal.aborted) {
                        // After a manual refresh a newer load owns the tile, and its status must stay with that load.
                        actions.stopWidgetRefreshes(
                            chunk.filter((tileId) => cache.widgetLoadSignals.get(tileId) === signal)
                        )
                        return
                    }
                    actions.setWidgetRefreshStatuses(chunk, false, DASHBOARD_WIDGET_FETCH_ERROR_MESSAGE)
                }
            })

            await Promise.all(fetchFunctions.map((fetchWidgets) => fetchWidgets()))
        },
        addWidgetTiles: async ({ dashboardId, widgets }) => {
            if (widgets.length === 0) {
                return
            }

            try {
                const previousWidgetTileIds = new Set(values.widgetTiles.map((tile) => tile.id))

                const widgetsPayload = widgets.map(({ widgetType, config }) => ({ widget_type: widgetType, config }))

                // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsWidgetsBatchCreate() from 'products/dashboards/frontend/generated/api' instead.
                const response = await api.create(
                    `api/projects/${teamLogic.values.currentTeamId}/dashboards/${dashboardId}/widgets/batch/`,
                    { widgets: widgetsPayload }
                )
                const createdTiles = findNewlyAddedWidgetTiles(previousWidgetTileIds, response.tiles)
                if (createdTiles.length > 0 && values.dashboard?.id === dashboardId) {
                    const dashboard = {
                        ...values.dashboard,
                        tiles: [...values.dashboard.tiles, ...createdTiles],
                    } as DashboardType
                    if (dashboard) {
                        dashboardsModel.actions.updateDashboardSuccess(dashboard)

                        actions.requestScrollToBottom()
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
        saveDashboardChanges: async () => {
            if (!values.dashboard || values.dashboardSettingsState !== 'unsavedChanges') {
                actions.saveDashboardChangesSuccess(null, null)
                return
            }

            const settings = values.currentDashboardSettings
            try {
                // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                const dashboard = await api.update(`api/projects/${values.currentTeamId}/dashboards/${props.id}`, {
                    filters: settings.filters,
                    variables: settings.variables,
                })
                actions.saveDashboardChangesSuccess(dashboard, settings)
                actions.clearDashboardSettingsUrlOverrides()
                actions.clearInitialDashboardSettingsOverride()
                if (!values.previewedDashboardSettings) {
                    actions.refreshDashboardItems({
                        action: RefreshDashboardItemsAction.Preview,
                        forceRefresh: false,
                    })
                }
                lemonToast.success('Dashboard changes saved')
            } catch (error) {
                actions.saveDashboardChangesFailure(String(error))
                lemonToast.error('Could not save dashboard changes: ' + String(error))
            }
        },
        discardDashboardChanges: () => {
            cache.pendingFilterChange = undefined
            actions.clearDashboardSettingsUrlOverrides()
            actions.clearInitialDashboardSettingsOverride()
            actions.setPreviewedDashboardSettings(null)
            actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Preview,
                forceRefresh: false,
            })
            exitFilterEditModeWhenSaved(values, actions)
        },
        saveDashboardChangesSuccess: () => {
            exitFilterEditModeWhenSaved(values, actions)
        },
        setDashboardSettingsDraft: () => {
            exitFilterEditModeWhenSaved(values, actions)
        },
        saveLayoutChanges: () => {
            if (values.hasUnsavedLayoutChanges) {
                actions.saveEditModeChanges('layout')
            }
            actions.setLayoutZoom(1)
            if (values.dashboardSettingsState === 'unsavedChanges') {
                actions.setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
            } else if (values.dashboardEditing !== null) {
                actions.setDashboardEditing(null, DashboardEventSource.DashboardFilters)
            }
        },
        saveDashboardColorChanges: () => {
            actions.saveEditModeChanges('colors')
        },
        discardLayoutChanges: () => {
            actions.cancelLayoutEdit()
        },
        saveLayout: () => {
            if (values.hasUnsavedLayoutChanges) {
                actions.saveEditModeChanges('layout')
            }
            actions.setLayoutZoom(1)
            if (values.dashboardSettingsState === 'unsavedChanges') {
                actions.setDashboardEditing({ filters: true, layout: false }, DashboardEventSource.DashboardFilters)
            } else if (values.dashboardEditing !== null) {
                actions.setDashboardEditing(null, DashboardEventSource.DashboardFilters)
            }
        },
        saveEditModeChangesFailure: () => {
            cache.resolveEditSaveApplied?.()
        },
        saveEditModeChangesSuccess: ({ dashboard, payload }) => {
            cache.resolveEditSaveApplied?.()
            // A failed or no-op save resolves with the dashboard from before the save, which holds unsaved moves.
            if (dashboard && payload?.scope !== 'colors' && cache.dashboardChangesPersisted) {
                // Sync the saved dashboard (including any name/description changes) to
                // dashboardsModel so the sidebar and other global views stay up to date
                dashboardsModel.actions.updateDashboardSuccess(dashboard, { layoutsPersisted: true })
            }
            if (
                dashboard &&
                payload?.scope === 'layout' &&
                values.draftLayouts === cache.draftLayoutsAtSave &&
                (cache.dashboardChangesPersisted || !values.hasUnsavedLayoutChanges)
            ) {
                actions.clearDraftLayouts()
            }
            cache.draftLayoutsAtSave = null
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
                    previewUnsavedFilters: true,
                })
            }
        },
        openAddInsightModal: () => {
            if (values.dashboardEditing?.layout && values.hasUnsavedLayoutChanges) {
                if (
                    !window.confirm(
                        'Discard unsaved layout changes?\nAdding an insight reloads the dashboard and discards them.'
                    )
                ) {
                    return
                }
                actions.setLayoutZoom(1)
                actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            }
            addInsightToDashboardLogic.actions.showAddInsightToDashboardModal()
        },
        cancelLayoutEdit: () => {
            const discard = (): void => {
                actions.setLayoutZoom(1)
                actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
            }
            const promptEnabled = !!values.featureFlags[FEATURE_FLAGS.DASHBOARD_LAYOUT_DISCARD_PROMPT]
            if (!promptEnabled || !(values.hasUnsavedLayoutChanges || values.hasUnsavedColorChanges)) {
                discard()
                return
            }
            eventUsageLogic.actions.reportDashboardEditModeDiscardPrompt(values.dashboard, 'shown')
            LemonDialog.open({
                title: 'Discard unsaved changes?',
                description:
                    'You have unsaved layout or color changes. If you discard now, the dashboard will revert to its last saved state.',
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
        changeDashboardTileSpacing: ({ tileSpacing }) => {
            if (tileSpacing === (values.dashboard?.customization?.tile_spacing ?? 'standard')) {
                return
            }
            actions.setDashboardTileSpacing(tileSpacing)
            actions.saveDashboardTileSpacing(tileSpacing)
        },
        changeDashboardGridCompaction: ({ layoutCompaction }) => {
            if (
                layoutCompaction ===
                (values.dashboard?.customization?.layout_compaction ?? DashboardGridCompaction.Vertical)
            ) {
                return
            }
            const changeCompaction = (discardUnsavedLayoutChanges = false): void => {
                if (discardUnsavedLayoutChanges && values.dashboard) {
                    actions.applyDashboardUpdate(
                        withSavedTilePlacements(values.dashboard, values.savedTilePlacements),
                        values.savedTilePlacements
                    )
                    actions.clearDraftLayouts()
                }
                actions.setDashboardGridCompaction(layoutCompaction)
                actions.saveDashboardGridCompaction(layoutCompaction)
            }

            if (!values.hasUnsavedLayoutChanges) {
                changeCompaction()
                return
            }

            actions.setDashboardCustomizeMenuOpen(false)
            LemonDialog.open({
                title: 'Change tile movement?',
                description: 'Changing this setting discards your unsaved tile layout changes.',
                primaryButton: {
                    children: 'Change mode',
                    onClick: () => changeCompaction(true),
                },
                secondaryButton: {
                    children: 'Cancel',
                },
            })
        },
        setDashboardEditing: async ({ editing, source }) => {
            if (
                editing === null &&
                source === DashboardEventSource.DashboardHeaderDiscardChanges &&
                values.dashboard?.tiles
            ) {
                actions.applyDashboardUpdate(
                    withSavedTilePlacements(values.dashboard, values.savedTilePlacements),
                    values.savedTilePlacements
                )
            }
            if (editing?.layout && source !== DashboardEventSource.DashboardHeaderDiscardChanges) {
                clearDOMTextSelection()
                lemonToast.info('Now editing the dashboard – press E or click Save to persist changes')
            } else if (
                editing === null &&
                (source === DashboardEventSource.DashboardHeaderSaveDashboard ||
                    source === DashboardEventSource.SceneCommonButtons ||
                    source === DashboardEventSource.DashboardInsightColorsModal)
            ) {
                if (source === DashboardEventSource.DashboardInsightColorsModal) {
                    actions.saveDashboardColorChanges()
                } else {
                    actions.saveLayoutChanges()
                }
            }

            if (editing?.layout) {
                eventUsageLogic.actions.reportDashboardLayoutEditModeEntered(
                    values.dashboard,
                    source,
                    values.layoutEditMode ? values.layoutZoom : null
                )
            }
        },
        setDashboardMode: async ({ mode, source }) => {
            if (mode || source) {
                eventUsageLogic.actions.reportDashboardModeToggled(
                    values.dashboard,
                    mode,
                    source,
                    values.layoutEditMode ? values.layoutZoom : null,
                    values.layoutEditMode
                )
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
                cache.onlineRecoveryPending = false
                cache.connectionRecoveryPending = false
                if (!values.dashboard) {
                    actions.dashboardNotFound()
                    return // We hit a 404
                }
            },
            sharedListeners.handleDashboardLoadComplete,
        ],
        loadDashboardMetadataSuccess: ({ dashboard }) => {
            cache.onlineRecoveryPending = false
            cache.connectionRecoveryPending = false
            if (!dashboard) {
                actions.dashboardNotFound()
                return // We hit a 404
            }
        },
        tileStreamingComplete: sharedListeners.handleDashboardLoadComplete,
        dashboardNotFound: () => {
            sceneLogic.findMounted()?.actions.resetUnavailableHomepage(urls.dashboard(props.id))
        },
        reportInsightsViewed: ({ insights }: { insights: InsightModel[] }) => {
            const insightIds = insights.map((insight: InsightModel) => insight?.id).filter((id): id is number => !!id)

            if (insightIds.length > 0 && values.currentTeamId && !isSharedView()) {
                // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. insightsViewedCreate() from 'products/product_analytics/frontend/generated/api' serves this route, but its generated types do not describe this call yet, so fix the endpoint's OpenAPI schema first.
                void api.create(`api/projects/${values.currentTeamId}/insights/viewed`, {
                    insight_ids: insightIds,
                })
            }
        },
        reportDashboardViewedEvent: ({ dashboard, lastRefreshed, delay }) => {
            clearTimeout(dashboardViewedTimeout)
            const captureDashboardView = (): void => {
                const properties = dashboardViewedProperties(dashboard, lastRefreshed, userLogic.values.user?.uuid)
                const eventName = delay ? 'dashboard analyzed' : 'viewed dashboard' // `viewed dashboard` name is kept for backwards compatibility
                posthog.capture(eventName, { ...properties, source: 'web' })
            }
            if (delay) {
                captureDashboardView()
            } else {
                dashboardViewedTimeout = setTimeout(captureDashboardView, 500) // Debounce to avoid noisy events from continuous navigation
            }
        },
        reportDashboardViewed: async (_, breakpoint) => {
            // Caching `dashboard`, as the dashboard might have unmounted after the breakpoint,
            // and "values.dashboard" will then fail
            const { dashboard, lastDashboardRefresh, tiles } = values
            if (dashboard) {
                actions.reportDashboardViewedEvent(dashboard, lastDashboardRefresh)

                const insights = tiles.map((t) => t.insight).filter((i): i is InsightModel => !!i)
                actions.reportInsightsViewed(insights)

                await breakpoint(IS_TEST_MODE ? 1 : 10000) // Tests will wait for all breakpoints to finish
                if (
                    router.values.location.pathname === urls.dashboard(dashboard.id) ||
                    router.values.location.pathname === urls.projectHomepage() ||
                    router.values.location.pathname.startsWith(urls.sharedDashboard(''))
                ) {
                    actions.reportDashboardViewedEvent(dashboard, lastDashboardRefresh, 10)
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
            abortWidgetLoads(cache)
            abortGroupLoads(cache)
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
        previewDashboardChanges: () => {
            actions.refreshDashboardItems({
                action: RefreshDashboardItemsAction.Preview,
                forceRefresh: false,
                previewUnsavedFilters: true,
            })
        },
        reportDashboardFilterChange: ({ changeType, properties }) => {
            const previousChange: PendingFilterChange | undefined = cache.pendingFilterChange
            const filterChange: PendingFilterChange = {
                id: uuid(),
                startTime: performance.now(),
                settings: values.currentDashboardSettings,
                remainingInsightIds: new Set(values.insightTiles.map((tile) => tile.insight!.short_id)),
            }
            cache.pendingFilterChange = filterChange
            eventUsageLogic.actions.reportDashboardFiltersChanged(values.dashboard, changeType, {
                ...properties,
                filter_change_id: filterChange.id,
                supersedes_filter_change_id: previousChange?.id,
                total_tile_count: values.insightTiles.length,
                can_auto_preview: values.canAutoPreview,
            })
        },
        setProperties: ({ properties }) => {
            actions.setDashboardSettingsDraft({
                ...values.currentDashboardSettings,
                filters: { ...values.currentDashboardSettings.filters, properties },
            })
            actions.reportDashboardFilterChange('properties', {
                property_count: properties?.length ?? 0,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
                })
            }
        },
        setDates: ({ dateFrom, dateTo, explicitDate }) => {
            actions.setDashboardSettingsDraft({
                ...values.currentDashboardSettings,
                filters: {
                    ...values.currentDashboardSettings.filters,
                    date_from: dateFrom,
                    date_to: dateTo,
                    explicitDate,
                },
            })
            actions.reportDashboardFilterChange('date', {
                date_from: dateFrom,
                date_to: dateTo ?? null,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
                })
            }
        },
        setBreakdownFilter: ({ breakdown_filter }) => {
            actions.setDashboardSettingsDraft({
                ...values.currentDashboardSettings,
                filters: { ...values.currentDashboardSettings.filters, breakdown_filter },
            })
            actions.reportDashboardFilterChange('breakdown', {
                breakdown_type: breakdown_filter?.breakdown_type ?? null,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
                })
            }
        },
        setInterval: ({ interval }) => {
            actions.setDashboardSettingsDraft({
                ...values.currentDashboardSettings,
                filters: { ...values.currentDashboardSettings.filters, interval },
            })
            actions.reportDashboardFilterChange('interval', {
                interval,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
                })
            }
        },
        setFilterTestAccounts: ({ filterTestAccounts }) => {
            actions.setDashboardSettingsDraft({
                ...values.currentDashboardSettings,
                filters: { ...values.currentDashboardSettings.filters, filterTestAccounts },
            })
            actions.reportDashboardFilterChange('test_accounts', {
                filter_test_accounts: filterTestAccounts,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
                })
            }
        },
        setCompareFilter: ({ compareFilter }) => {
            actions.setDashboardSettingsDraft({
                ...values.currentDashboardSettings,
                filters: { ...values.currentDashboardSettings.filters, compareFilter },
            })
            actions.reportDashboardFilterChange('compare', {
                compare: compareFilter?.compare ?? null,
                compare_to: compareFilter?.compare_to ?? null,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
                })
            }
        },
        setMetricVariables: ({ metricVariables }) => {
            actions.setDashboardSettingsDraft({
                ...values.currentDashboardSettings,
                filters: { ...values.currentDashboardSettings.filters, metricVariables },
            })
            actions.reportDashboardFilterChange('metric_variables', {
                metric_variable_count: metricVariables?.length ?? 0,
                metric_variable_query_count:
                    metricVariables?.filter((variable) => variable.source === 'promql' || variable.source === 'sql')
                        .length ?? 0,
            })

            // The builtin placement has no Preview button, so a selection there always applies.
            if (values.canAutoPreview || values.placement === DashboardPlacement.Builtin) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
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
        overrideVariableValue: ({ variableId, value, isNull }) => {
            const variableDefinition = values.variables.find((candidate) => candidate.id === variableId)
            if (variableDefinition) {
                const variable = { code_name: variableDefinition.code_name, variableId, value, isNull }
                const variables = { ...values.currentDashboardSettings.variables }
                if (
                    dashboardVariableValuesEqual(variable, {
                        value: variableDefinition.default_value,
                        isNull: variableDefinition.isNull,
                    })
                ) {
                    delete variables[variableId]
                } else {
                    variables[variableId] = variable
                }
                actions.setDashboardSettingsDraft({
                    ...values.currentDashboardSettings,
                    variables,
                })
            }

            actions.reportDashboardFilterChange('variable', {
                variable_id: variableId,
            })

            if (values.canAutoPreview) {
                actions.refreshDashboardItems({
                    action: RefreshDashboardItemsAction.Preview,
                    forceRefresh: false,
                    previewUnsavedFilters: true,
                })
            }
            if (values.dashboardSettingsState === 'unsavedChanges' && !values.dashboardEditing?.filters) {
                actions.setDashboardEditing(
                    { filters: true, layout: false },
                    DashboardEventSource.DashboardVariableOverride
                )
            }
        },
        [variableDataLogic.actionTypes.loadVariablesSuccess]: ({ variables }) => {
            const urlVariableValues = parseURLVariables(router.values.searchParams)
            const initialVariables = Object.fromEntries(
                variables.flatMap((variable: Variable) => {
                    if (!(variable.code_name in urlVariableValues)) {
                        return []
                    }
                    const value = urlVariableValues[variable.code_name]
                    return [
                        [
                            variable.id,
                            {
                                code_name: variable.code_name,
                                variableId: variable.id,
                                value,
                                isNull: value === null,
                            },
                        ],
                    ]
                })
            )
            actions.setInitialDashboardSettingsOverride({
                ...values.initialDashboardSettingsOverride,
                variables: initialVariables,
            })
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
                maxWidth: '40rem',
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
                    const wasIgnored = !!tile.filters_overrides?.ignoreDashboardFilters
                    const isIgnored = !!tileFilterOverrides.ignoreDashboardFilters

                    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a hand-written URL and an unchecked response type. Use dashboardsPartialUpdate() from 'products/dashboards/frontend/generated/api' instead.
                    await api.update(`api/projects/${teamLogic.values.currentTeamId}/dashboards/${props.id}`, {
                        tiles: [{ id: tile.id, filters_overrides: tileFilterOverrides }],
                    })

                    tile.filters_overrides = tileFilterOverrides
                    if (wasIgnored !== isIgnored) {
                        posthog.capture('dashboard tile ignore dashboard filters toggled', {
                            dashboard_id: props.id,
                            insight_id: tile.insight?.id ?? null,
                            ignored: isIgnored,
                        })
                    }
                    actions.refreshDashboardItem({ tile })
                    lemonToast.success('Tile filters saved')
                },
            })
        },
    })),

    beforeUnload(({ values, actions }) => ({
        enabled: (newLocation?: CombinedLocation) => {
            if (!values.dashboardEditing?.layout || !values.hasUnsavedLayoutChanges) {
                return false
            }
            // Ignore in-page navigations such as opening a side panel
            if (newLocation && newLocation.pathname === router.values.location.pathname) {
                return false
            }
            return true
        },
        message: 'Leave dashboard?\nChanges you made to the layout will be discarded.',
        onConfirm: () => {
            actions.setDashboardEditing(null, DashboardEventSource.DashboardHeaderDiscardChanges)
        },
    })),

    actionToUrl(({ values }) => ({
        setProperties: ({ properties }) => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                properties,
            }

            return [
                currentLocation.pathname,
                searchParamsWithUrlFilters(
                    currentLocation.searchParams,
                    newUrlFilters,
                    combineDashboardFilters(values.dashboard?.persisted_filters || {}, values.externalFilters)
                ),
                currentLocation.hashParams,
            ]
        },
        setDates: ({ dateFrom, dateTo, explicitDate }) => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                date_from: dateFrom,
                date_to: dateTo,
                explicitDate,
            }

            return [
                currentLocation.pathname,
                searchParamsWithUrlFilters(
                    currentLocation.searchParams,
                    newUrlFilters,
                    combineDashboardFilters(values.dashboard?.persisted_filters || {}, values.externalFilters)
                ),
                currentLocation.hashParams,
            ]
        },
        setBreakdownFilter: ({ breakdown_filter }) => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                breakdown_filter,
            }

            return [
                currentLocation.pathname,
                searchParamsWithUrlFilters(
                    currentLocation.searchParams,
                    newUrlFilters,
                    combineDashboardFilters(values.dashboard?.persisted_filters || {}, values.externalFilters)
                ),
                currentLocation.hashParams,
            ]
        },
        setInterval: ({ interval }) => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                interval,
            }

            return [
                currentLocation.pathname,
                searchParamsWithUrlFilters(
                    currentLocation.searchParams,
                    newUrlFilters,
                    combineDashboardFilters(values.dashboard?.persisted_filters || {}, values.externalFilters)
                ),
                currentLocation.hashParams,
            ]
        },
        setFilterTestAccounts: ({ filterTestAccounts }) => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                filterTestAccounts,
            }

            return [
                currentLocation.pathname,
                searchParamsWithUrlFilters(
                    currentLocation.searchParams,
                    newUrlFilters,
                    combineDashboardFilters(values.dashboard?.persisted_filters || {}, values.externalFilters)
                ),
                currentLocation.hashParams,
            ]
        },
        setCompareFilter: ({ compareFilter }) => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                compareFilter,
            }

            return [
                currentLocation.pathname,
                searchParamsWithUrlFilters(
                    currentLocation.searchParams,
                    newUrlFilters,
                    combineDashboardFilters(values.dashboard?.persisted_filters || {}, values.externalFilters)
                ),
                currentLocation.hashParams,
            ]
        },
        setMetricVariables: ({ metricVariables }) => {
            const { currentLocation } = router.values

            const urlFilters = parseURLFilters(currentLocation.searchParams)
            const newUrlFilters: DashboardFilter = {
                ...urlFilters,
                metricVariables,
            }

            return [
                currentLocation.pathname,
                searchParamsWithUrlFilters(
                    currentLocation.searchParams,
                    newUrlFilters,
                    combineDashboardFilters(values.dashboard?.persisted_filters || {}, values.externalFilters)
                ),
                currentLocation.hashParams,
            ]
        },
        overrideVariableValue: ({ variableId, value, isNull }) => {
            const { currentLocation } = router.values

            const currentVariable = values.variables.find((variable: Variable) => variable.id === variableId)

            if (!currentVariable) {
                return [currentLocation.pathname, currentLocation.searchParams, currentLocation.hashParams]
            }

            const newUrlVariables = { ...parseURLVariables(currentLocation.searchParams) }
            // An absent URL entry means "use the saved value", so the entry can only be dropped when
            // the choice matches what the dashboard saved. A dashboard without a saved value shows the
            // project default, which keeps the URL clean for the common case.
            const savedValue = values.savedDashboardSettings.variables[variableId] ?? {
                value: currentVariable.default_value,
                isNull: currentVariable.isNull,
            }
            if (dashboardVariableValuesEqual({ value, isNull }, savedValue)) {
                delete newUrlVariables[currentVariable.code_name]
            } else {
                newUrlVariables[currentVariable.code_name] = value
            }

            const newSearchParams = {
                ...currentLocation.searchParams,
            }
            delete newSearchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY]

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
        clearDashboardSettingsUrlOverrides: () => {
            const { currentLocation } = router.values
            const newSearchParams = { ...currentLocation.searchParams }
            delete newSearchParams[SEARCH_PARAM_FILTERS_KEY]
            delete newSearchParams[SEARCH_PARAM_QUERY_VARIABLES_KEY]
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
            actions.setButtonTileId(null)
            actions.setDashboardMode(null, DashboardEventSource.Browser)
            actions.setDashboardEditing(null, DashboardEventSource.Browser)
        },

        '/dashboard/:id': (_params, searchParams, _hashParams, { method }) => {
            actions.revealHighlightedInsight()
            actions.setSubscriptionMode(false, undefined)
            actions.setTextTileId(null)
            actions.setButtonTileId(null)
            if (method === 'POP' && values.dashboard) {
                const current = values.currentDashboardSettings
                const settings: DashboardSettings = {
                    filters: combineSavedAndUrlFilters(
                        values.savedDashboardSettings.filters,
                        parseURLFilters(searchParams)
                    ),
                    // Browser history carries SQL variables as well as filters. Until the variable
                    // definitions load there is nothing to map the URL values onto, so the current
                    // values stay.
                    variables: values.initialVariablesLoaded
                        ? { ...values.savedDashboardSettings.variables, ...values.urlVariables }
                        : current.variables,
                }

                // Back and Forward also arrive from routes that leave the settings alone, such as the
                // sharing page. Rebuilding the settings there would re-query every tile and cancel a
                // refresh in flight for values the dashboard already holds.
                if (
                    !dashboardFiltersEqual(current.filters, settings.filters) ||
                    !equal(current.variables, settings.variables)
                ) {
                    actions.setDashboardSettingsDraft(settings)
                    if (values.canAutoPreview) {
                        actions.refreshDashboardItems({
                            action: RefreshDashboardItemsAction.Preview,
                            forceRefresh: false,
                        })
                    }
                }
            }
            if (values.dashboardMode === DashboardMode.Sharing) {
                actions.setDashboardMode(null, DashboardEventSource.Browser)
            }
            switch (searchParams.tileType) {
                case 'text':
                    actions.openTextTileModal()
                    break
                case 'image':
                    actions.openImageTileModal()
                    break
                case 'button':
                    actions.openButtonTileModal()
                    break
            }
        },
        '/dashboard/:id/sharing': () => {
            actions.setSubscriptionMode(false, undefined)
            actions.setTextTileId(null)
            actions.setButtonTileId(null)
            actions.setDashboardMode(DashboardMode.Sharing, DashboardEventSource.Browser)
        },
        '/dashboard/:id/tiles/:tileId': ({ tileId }) => {
            actions.setSubscriptionMode(false, undefined)
            actions.setDashboardMode(null, DashboardEventSource.Browser)
            actions.setDashboardEditing(null, DashboardEventSource.Browser)
            const parsedTileId = parseDashboardTileId(tileId)
            actions.setTextTileId(parsedTileId)
            actions.setButtonTileId(parsedTileId)
        },
    })),
])

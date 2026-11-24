import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import type { BuiltLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { dashboardsModel } from '~/models/dashboardsModel'
import type { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { MetricsQuery, NodeKind } from '~/queries/schema/schema-general'
import { DashboardPlacement } from '~/types'
import type { DashboardTile, InsightModel } from '~/types'

import { streamDashboardQueryResults } from 'products/dashboards/frontend/streamDashboardQueryResults'
import type { DashboardStreamResultTiming } from 'products/dashboards/frontend/streamDashboardQueryResults'

import type { DashboardLogicProps, DashboardSettings, TileLoadRefresh } from './dashboardLogic'
import {
    RATE_LIMITED_ERROR_CODE,
    RATE_LIMIT_ERROR_MESSAGE,
    TaskQueue,
    type TileLoads,
    getInsightQueryError,
    isRefreshRejectionStub,
} from './dashboardUtils'

// With dashboard-v2, metrics tiles run in the server's own per-organization telemetry slots
// (DEFAULT_APP_TELEMETRY_CONCURRENT_QUERIES), apart from the analytics slots. One tab takes half
// of them, so a second viewer in the organization doesn't queue behind it.
const TELEMETRY_TILE_REFRESH_CONCURRENCY = 6
// With dashboard-v2, a first load queries this many tiles up front, in layout order.
// The rest load when they scroll near the viewport.
const EAGER_TILE_LOADS = 12
// Matches MAX_CACHED_TILES_BATCH_SIZE: the most tiles one board stream takes.
const BOARD_STREAM_MAX_TILES = 100
// Tiles that scroll into view within this window load through one board stream.
const SCROLL_IN_BATCH_MS = 100

export function telemetryTileLoadQueue(cache: Record<string, any>): TaskQueue {
    return (cache.telemetryTileLoadQueue ??= new TaskQueue(TELEMETRY_TILE_REFRESH_CONCURRENCY))
}

// Mirrors DERIVED_METRIC_PREFIX in products/metrics/backend/facade/contracts.py.
const DERIVED_METRIC_PREFIX = 'posthog.derived.'

/**
 * Whether the server runs this tile in the telemetry slots, mirroring `MetricsQueryRunner._query_lane`.
 * Derived metrics scan spans or logs, and histograms have no lane of their own, so both take the analytics slots
 * and must wait in the analytics queue.
 */
export function isTelemetryInsight(insight: InsightModel): boolean {
    const query = insight.query
    if (query?.kind !== NodeKind.MetricsQuery) {
        return false
    }
    return !(query as MetricsQuery).clauses?.some((clause) => clause.metricName?.startsWith(DERIVED_METRIC_PREFIX))
}

interface OffscreenTileSplit<T extends DashboardTile> {
    tilesToRefresh: T[]
    deferredTileIds: number[]
}

interface OffscreenTileRefresh {
    isInitialLoad: boolean
    forceRefresh: boolean
    isAutomatic: boolean
    onDashboardPage: boolean
}

/**
 * Splits a refresh into the tiles to query now and the tiles to query once they scroll into view.
 * Only a first load and an automatic refresh on the dashboard page defer tiles. Every other refresh queries them all.
 */
function splitOffscreenTiles<T extends DashboardTile>(
    tiles: T[],
    {
        isInitialLoad,
        forceRefresh,
        isAutomatic,
        onDashboardPage,
        tilesInView,
        visibilityReported,
    }: OffscreenTileRefresh & {
        tilesInView: Set<number>
        visibilityReported: boolean
    }
): OffscreenTileSplit<T> {
    const split = (shouldLoadNow: (tile: T, index: number) => boolean): OffscreenTileSplit<T> => ({
        tilesToRefresh: tiles.filter(shouldLoadNow),
        deferredTileIds: tiles.filter((tile, index) => !shouldLoadNow(tile, index)).map((tile) => tile.id),
    })
    if (!onDashboardPage) {
        return { tilesToRefresh: tiles, deferredTileIds: [] }
    }
    if (isInitialLoad && !forceRefresh && tiles.length > EAGER_TILE_LOADS) {
        // A tile past the first screen that already reported itself in view will not report again, so it loads now.
        return split((tile, index) => index < EAGER_TILE_LOADS || tilesInView.has(tile.id))
    }
    // Until a tile reports its visibility, an automatic refresh queries every tile.
    // Once tiles have reported, an empty view (only text or widgets on screen) defers every insight.
    if (isAutomatic && visibilityReported) {
        return split((tile) => tilesInView.has(tile.id))
    }
    return { tilesToRefresh: tiles, deferredTileIds: [] }
}

export function deferOffscreenTiles<T extends DashboardTile>(
    logic: BuiltLogic<dashboardV2LogicType>,
    tiles: T[],
    refresh: OffscreenTileRefresh & { settings: DashboardSettings }
): T[] {
    const { deferredTileIds, tilesToRefresh } = splitOffscreenTiles(tiles, {
        ...refresh,
        tilesInView: new Set(logic.values.tilesInView),
        visibilityReported: logic.values.tileVisibilityReported,
    })
    logic.actions.setDeferredTileIds(deferredTileIds, refresh.forceRefresh, refresh.settings)
    return tilesToRefresh
}

type InsightTile = DashboardTile & { insight: InsightModel }

function usesBoardStream(placement: DashboardPlacement, tileCount: number): boolean {
    return (
        placement === DashboardPlacement.Dashboard &&
        !isSharedView() &&
        tileCount > 0 &&
        tileCount <= BOARD_STREAM_MAX_TILES
    )
}

/**
 * A first load on the dashboard page reads tile results through the board stream,
 * so the dashboard GET returns the layout and tile metadata only.
 */
export function omitsTileResultsOnLoad(
    dashboardV2Enabled: boolean,
    isInitialLoad: boolean,
    placement: DashboardPlacement
): boolean {
    return dashboardV2Enabled && isInitialLoad && placement === DashboardPlacement.Dashboard && !isSharedView()
}

/** The refresh a board stream runs for, as the per-tile path receives it. */
export interface BoardStreamRefresh {
    actions: {
        setRefreshStatus: (shortId: InsightModel['short_id'], loading?: boolean, queued?: boolean) => void
        setRefreshError: (shortId: InsightModel['short_id'], error?: any) => void
    }
    dashboardId: number
    currentTeamId: number | null
    filters: DashboardFilter
    variables: Record<string, HogQLVariable>
    urlFilters: DashboardFilter
    forceRefresh: boolean
    isAutomatic?: boolean
    signal: AbortSignal
}

/** Records a delivered tile with the same event the per-tile path sends. */
export type TileRefreshReporter = (
    dashboardId: number,
    tile: DashboardTile,
    servedFromCache: boolean | undefined,
    filters: Record<string, any>,
    variables: Record<string, any>,
    refreshDurationMs: number,
    individualRefresh: boolean,
    requestTiming: undefined,
    loadTiming: { queueWaitMs: number; requestMs: number; dashboardV2Ui: boolean },
    filterChange: undefined,
    isAutomatic: boolean | undefined,
    eventProperties: Record<string, unknown>
) => void

type TileOutcome = 'refreshed' | 'cached' | 'errored'

export interface BoardStreamOutcome<T extends InsightTile> {
    settledTileIds: Set<number>
    /** The tiles the stream did not settle. The caller loads them through the per-tile path. */
    leftTiles: T[]
    /** The refresh was cancelled while the stream ran. */
    aborted: boolean
    /**
     * How the per-tile path loads `leftTiles`: one request each, because the stream already waited for query capacity
     * and the per-tile retries would wait again.
     */
    fallback: { eventProperties: Record<string, unknown>; maxAttempts?: number; asyncFallback?: boolean }
    /** For the `dashboard refreshed` event. */
    refreshEventProperties: Record<string, unknown>
}

export interface RefreshBoardStreamOutcome<T extends InsightTile> extends BoardStreamOutcome<T> {
    /** A tab switch stopped the stream. Its `leftTiles` wait for their tab to show again. */
    stopped: boolean
    /** The stream's query id and start time, for reporting the tiles it left as aborted. */
    queryId: string
    startedAt: number
}

interface BoardStreamLoad<T extends InsightTile> {
    refresh: BoardStreamRefresh
    teamId: number
    queryId: string
    report: TileRefreshReporter
    settle: (tile: T, outcome: TileOutcome) => void
}

function rejectedForCapacity(insight: InsightModel): boolean {
    return (
        insight.query_status?.error_code === RATE_LIMITED_ERROR_CODE ||
        insight.query_status?.error_message === RATE_LIMIT_ERROR_MESSAGE
    )
}

/**
 * Loads tiles through one stream: its first event paints every cached result, stale ones included, and the stream
 * then delivers each tile it computes. A stale tile stays loading until its computed result replaces it.
 * A tile the server had no capacity for, and every tile a failed stream did not deliver, stays unsettled.
 */
async function loadThroughBoardStream<T extends InsightTile>(
    tiles: T[],
    load: BoardStreamLoad<T>
): Promise<BoardStreamOutcome<T>> {
    const { refresh } = load
    const { actions, dashboardId, signal } = refresh
    const tilesById = new Map(tiles.map((tile) => [tile.id, tile]))
    const settledTileIds = new Set<number>()
    const startedAt = performance.now()
    const settleLoaded = (
        tile: T,
        insight: InsightModel,
        isCached: boolean,
        timing: DashboardStreamResultTiming
    ): void => {
        settledTileIds.add(tile.id)
        dashboardsModel.actions.updateDashboardInsight(insight, undefined, dashboardId)
        actions.setRefreshStatus(tile.insight.short_id)
        load.report(
            dashboardId,
            tile,
            isCached,
            refresh.urlFilters,
            refresh.variables,
            Math.floor(performance.now() - startedAt),
            false,
            // An open stream has no completed-response or resource timing for this tile.
            undefined,
            { queueWaitMs: 0, requestMs: Math.floor(timing.requestToResultMs), dashboardV2Ui: true },
            undefined,
            refresh.isAutomatic,
            {
                stream_fallback: false,
                request_timing_scope: 'stream_start_to_result',
                ...(timing.httpRequestId ? { http_request_id: timing.httpRequestId } : {}),
            }
        )
        load.settle(tile, isCached ? 'cached' : 'refreshed')
    }
    const settleErrored = (tile: T, error?: any): void => {
        settledTileIds.add(tile.id)
        actions.setRefreshError(tile.insight.short_id, error)
        load.settle(tile, 'errored')
    }
    try {
        await streamDashboardQueryResults(
            load.teamId,
            dashboardId,
            {
                tile_ids: tiles.map((tile) => tile.id).join(','),
                client_query_id: load.queryId,
                refresh: refresh.forceRefresh ? 'force_blocking' : 'blocking',
                cached_first: true,
                filters_override: JSON.stringify(refresh.filters),
                variables_override: JSON.stringify(refresh.variables),
            },
            signal,
            (result, _debug, timing) => {
                const tile = result.id !== undefined ? tilesById.get(result.id) : undefined
                if (signal.aborted || !tile || settledTileIds.has(tile.id)) {
                    return
                }
                if ('error' in result || !result.insight) {
                    settleErrored(tile)
                    return
                }
                const insight = result.insight as unknown as InsightModel
                if (rejectedForCapacity(insight)) {
                    return
                }
                const queryError = getInsightQueryError(insight)
                if (queryError || isRefreshRejectionStub(insight)) {
                    settleErrored(tile, queryError?.code ? queryError : undefined)
                    return
                }
                settleLoaded(tile, insight, !!insight.is_cached, timing)
            },
            ({ tiles: cachedTiles, pending }, timing) => {
                if (signal.aborted) {
                    return
                }
                const pendingIds = new Set(pending)
                for (const entry of cachedTiles) {
                    const tile = tilesById.get(entry.id)
                    if (!tile || settledTileIds.has(tile.id)) {
                        continue
                    }
                    const insight =
                        entry.status === 'hit' && entry.insight
                            ? ({ ...tile.insight, ...entry.insight } as unknown as InsightModel)
                            : null
                    if (pendingIds.has(tile.id)) {
                        if (insight) {
                            dashboardsModel.actions.updateDashboardInsight(insight, undefined, dashboardId)
                        }
                    } else if (insight) {
                        settleLoaded(tile, insight, true, timing)
                    } else {
                        settleErrored(tile)
                    }
                }
            }
        )
        return boardStreamOutcome(tiles, settledTileIds, false, signal.aborted)
    } catch {
        return boardStreamOutcome(tiles, settledTileIds, !signal.aborted, signal.aborted)
    }
}

function boardStreamOutcome<T extends InsightTile>(
    tiles: T[],
    settledTileIds: Set<number>,
    failed: boolean,
    aborted: boolean
): BoardStreamOutcome<T> {
    const leftTiles = tiles.filter((tile) => !settledTileIds.has(tile.id))
    return {
        settledTileIds,
        leftTiles,
        aborted,
        fallback: { eventProperties: { stream_fallback: true }, maxAttempts: 1, asyncFallback: false },
        refreshEventProperties: { board_stream: true, stream_fallback: leftTiles.length > 0, stream_failed: failed },
    }
}

/**
 * With dashboard-v2, a refresh on the dashboard page loads its tiles through one board stream.
 * Null when the stream does not apply, and the refresh loads every tile through the per-tile path.
 */
export async function refreshThroughBoardStream<T extends InsightTile>(
    cache: Record<string, any>,
    tiles: T[],
    refresh: BoardStreamRefresh & { tileLoads: TileLoads<TileLoadRefresh>; settings: DashboardSettings },
    {
        placement,
        report,
        settle,
    }: { placement: DashboardPlacement; report: TileRefreshReporter; settle: (tile: T, outcome: TileOutcome) => void }
): Promise<RefreshBoardStreamOutcome<T> | null> {
    if (!refresh.currentTeamId || !usesBoardStream(placement, tiles.length)) {
        return null
    }
    // Registered with tileLoads, so a tab switch that stops the loads of the tab a viewer leaves stops this stream.
    const tileLoad = refresh.tileLoads.start(
        tiles.map((tile) => tile.id),
        refresh.signal,
        { forceRefresh: refresh.forceRefresh, settings: refresh.settings }
    )
    const controller = new AbortController()
    tileLoad.signal.addEventListener('abort', () => controller.abort(), { once: true })
    cache.disposables.add(() => () => controller.abort(), 'dashboard-board-stream', { pauseOnPageHidden: false })
    const queryId = uuid()
    const startedAt = performance.now()
    try {
        const outcome = await loadThroughBoardStream(tiles, {
            refresh: { ...refresh, signal: controller.signal },
            teamId: refresh.currentTeamId,
            queryId,
            report,
            settle: (tile, tileOutcome) => {
                tileLoad.release(tile.id)
                settle(tile, tileOutcome)
            },
        })
        const stopped = tileLoad.signal.aborted && !refresh.signal.aborted
        return { ...outcome, aborted: outcome.aborted && !stopped, stopped, queryId, startedAt }
    } finally {
        tileLoad.finish()
    }
}

/**
 * Loads tiles that scrolled into view. The tiles that arrive within one short window load through one board stream.
 * Each call restarts the window: `breakpoint` cancels the earlier calls, and the last call loads every waiting tile.
 * The caller marks each tile as loading before this waits, so a card that mounts meanwhile does not start its own query.
 * Null when the board stream does not apply, and the caller loads the tiles through the per-tile path.
 */
export async function loadScrolledInTiles<T extends InsightTile>(
    cache: Record<string, any>,
    tiles: T[],
    refresh: BoardStreamRefresh,
    {
        placement,
        report,
        breakpoint,
    }: {
        placement: DashboardPlacement
        report: TileRefreshReporter
        breakpoint: (ms: number) => Promise<void> | void
    }
): Promise<BoardStreamOutcome<T> | null> {
    if (!refresh.currentTeamId || !usesBoardStream(placement, tiles.length)) {
        return null
    }
    const waiting: T[] = (cache.scrolledInTiles ??= [])
    waiting.push(...tiles.filter((tile) => !waiting.some((other) => other.id === tile.id)))
    await breakpoint(SCROLL_IN_BATCH_MS)
    cache.scrolledInTiles = []
    // The stream only sees aborts that happen after it starts, so a refresh cancelled during the debounce skips it.
    const aborted = refresh.signal.aborted
    if (aborted || !usesBoardStream(placement, waiting.length)) {
        return {
            settledTileIds: new Set(),
            leftTiles: waiting,
            aborted,
            fallback: { eventProperties: {} },
            refreshEventProperties: {},
        }
    }
    return await loadThroughBoardStream(waiting, {
        refresh,
        teamId: refresh.currentTeamId,
        queryId: uuid(),
        report,
        settle: () => {},
    })
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardV2LogicValues {
    featureFlags: FeatureFlagsSet // featureFlagLogic
    dashboardV2Enabled: boolean
    deferredTileIds: number[]
    deferredTilesForceRefresh: boolean
    deferredTilesSettings: DashboardSettings | null
    tileVisibilityReported: boolean
    tilesInView: number[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardV2LogicActions {
    loadDeferredTiles: (tileIds: number[]) => {
        tileIds: number[]
    }
    refreshDeferredTiles: (
        tileIds: number[],
        forceRefresh: boolean,
        settings: DashboardSettings | null
    ) => {
        forceRefresh: boolean
        settings: DashboardSettings | null
        tileIds: number[]
    }
    setDeferredTileIds: (
        tileIds: number[],
        forceRefresh?: boolean,
        settings?: DashboardSettings | null
    ) => {
        forceRefresh: boolean
        settings: DashboardSettings | null
        tileIds: number[]
    }
    setTileInView: (
        tileId: number,
        inView: boolean
    ) => {
        inView: boolean
        tileId: number
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface dashboardV2LogicMeta {
    key: number | 'invalid'
    __keaTypeGenInternalSelectorTypes: {
        dashboardV2Enabled: (featureFlags: FeatureFlagsSet) => boolean
    }
}

export type dashboardV2LogicType = MakeLogicType<
    dashboardV2LogicValues,
    dashboardV2LogicActions,
    DashboardLogicProps,
    dashboardV2LogicMeta
>

export const dashboardV2Logic = kea<dashboardV2LogicType>([
    path(['scenes', 'dashboard', 'dashboardV2Logic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),

    props({ id: NaN } as DashboardLogicProps),

    key((props) => {
        if (!Number.isFinite(props.id)) {
            return 'invalid'
        }
        return props.id
    }),

    actions(() => ({
        /** Tiles a refresh skipped because they were off screen, and whether that refresh forced fresh results. */
        setDeferredTileIds: (
            tileIds: number[],
            forceRefresh: boolean = false,
            settings: DashboardSettings | null = null
        ) => ({ tileIds, forceRefresh, settings }),
        setTileInView: (tileId: number, inView: boolean) => ({ tileId, inView }),
        loadDeferredTiles: (tileIds: number[]) => ({ tileIds }),
        refreshDeferredTiles: (tileIds: number[], forceRefresh: boolean, settings: DashboardSettings | null) => ({
            tileIds,
            forceRefresh,
            settings,
        }),
    })),

    reducers(() => ({
        deferredTileIds: [
            [] as number[],
            {
                setDeferredTileIds: (_, { tileIds }) => tileIds,
            },
        ],
        deferredTilesForceRefresh: [
            false,
            {
                setDeferredTileIds: (_, { forceRefresh }) => forceRefresh,
            },
        ],
        // The settings of the refresh that skipped the tiles, so a tile that loads later matches the tiles around it.
        deferredTilesSettings: [
            null as DashboardSettings | null,
            {
                setDeferredTileIds: (_, { settings }) => settings,
            },
        ],
        // Whether any tile has reported its visibility, so an empty view is not mistaken for unknown visibility.
        tileVisibilityReported: [
            false,
            {
                setTileInView: () => true,
            },
        ],
        tilesInView: [
            [] as number[],
            {
                setTileInView: (state, { tileId, inView }) =>
                    inView
                        ? state.includes(tileId)
                            ? state
                            : [...state, tileId]
                        : state.filter((id) => id !== tileId),
            },
        ],
    })),

    selectors(() => ({
        // dashboard-v2 (by project) turns the behaviour on; dashboard-v2-users (by person) picks who sees it.
        dashboardV2Enabled: [
            (s) => [s.featureFlags],
            (featureFlags: FeatureFlagsSet): boolean =>
                !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2] && !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2_USERS],
        ],
    })),

    listeners(({ actions, values }) => ({
        setTileInView: ({ tileId, inView }) => {
            if (inView) {
                actions.loadDeferredTiles([tileId])
            }
        },
        loadDeferredTiles: ({ tileIds }) => {
            const deferred = values.deferredTileIds.filter((tileId) => tileIds.includes(tileId))
            if (deferred.length === 0) {
                return
            }
            const forceRefresh = values.deferredTilesForceRefresh
            const settings = values.deferredTilesSettings
            actions.setDeferredTileIds(
                values.deferredTileIds.filter((tileId) => !deferred.includes(tileId)),
                forceRefresh,
                settings
            )
            actions.refreshDeferredTiles(deferred, forceRefresh, settings)
        },
    })),
])

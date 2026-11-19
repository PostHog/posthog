import { MakeLogicType, actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import type { BuiltLogic } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { uuid } from 'lib/utils/dom'

import { dashboardsModel } from '~/models/dashboardsModel'
import type { DashboardFilter, HogQLVariable } from '~/queries/schema/schema-general'
import { MetricsQuery, NodeKind } from '~/queries/schema/schema-general'
import type { DashboardTile, InsightModel } from '~/types'

import { streamDashboardQueryResults } from 'products/dashboards/frontend/streamDashboardQueryResults'

import type { DashboardLogicProps, DashboardSettings } from './dashboardLogic'
import {
    RATE_LIMITED_ERROR_CODE,
    RATE_LIMIT_ERROR_MESSAGE,
    TaskQueue,
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

/** With dashboard-v2, a refresh on the dashboard page loads its tiles through one board stream. */
export function usesBoardStream(dashboardV2Enabled: boolean, onDashboardPage: boolean, tileCount: number): boolean {
    return dashboardV2Enabled && onDashboardPage && tileCount > 0 && tileCount <= BOARD_STREAM_MAX_TILES
}

export interface BoardStreamLoad<T extends InsightTile> {
    actions: {
        setRefreshStatus: (shortId: InsightModel['short_id'], loading?: boolean, queued?: boolean) => void
        setRefreshError: (shortId: InsightModel['short_id'], error?: any) => void
    }
    teamId: number
    dashboardId: number
    forceRefresh: boolean
    filters: DashboardFilter
    variables: Record<string, HogQLVariable>
    signal: AbortSignal
    /** Records a tile the stream delivered, as the per-tile path records each tile it loads. */
    reportTile: (tile: T, isCached: boolean, durationMs: number) => void
    settle: (tile: T, outcome: 'refreshed' | 'cached' | 'errored') => void
}

export interface BoardStreamResult {
    /** The tiles the stream settled. The caller loads every other tile through the per-tile path. */
    settledTileIds: Set<number>
    failed: boolean
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
export async function loadThroughBoardStream<T extends InsightTile>(
    tiles: T[],
    load: BoardStreamLoad<T>
): Promise<BoardStreamResult> {
    const { actions, dashboardId, signal } = load
    const tilesById = new Map(tiles.map((tile) => [tile.id, tile]))
    const settledTileIds = new Set<number>()
    const startedAt = performance.now()
    const settleLoaded = (tile: T, insight: InsightModel, isCached: boolean): void => {
        settledTileIds.add(tile.id)
        dashboardsModel.actions.updateDashboardInsight(insight, undefined, dashboardId)
        actions.setRefreshStatus(tile.insight.short_id)
        load.reportTile(tile, isCached, Math.floor(performance.now() - startedAt))
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
                client_query_id: uuid(),
                refresh: load.forceRefresh ? 'force_blocking' : 'blocking',
                cached_first: true,
                filters_override: JSON.stringify(load.filters),
                variables_override: JSON.stringify(load.variables),
            },
            signal,
            (result) => {
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
                settleLoaded(tile, insight, !!insight.is_cached)
            },
            ({ tiles: cachedTiles, pending }) => {
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
                        settleLoaded(tile, insight, true)
                    } else {
                        settleErrored(tile)
                    }
                }
            }
        )
        return { settledTileIds, failed: false }
    } catch {
        return { settledTileIds, failed: !signal.aborted }
    }
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

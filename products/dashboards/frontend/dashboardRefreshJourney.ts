import type {
    CustomerJourney,
    CustomerJourneyEndReason,
    CustomerJourneyInsightType,
    CustomerJourneySummary,
    CustomerJourneyTileResult,
} from 'lib/customerJourneys/createCustomerJourney'
import { CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT } from 'lib/customerJourneys/createCustomerJourney'
import { startCustomerJourney } from 'lib/customerJourneys/startCustomerJourney'

import { NodeKind } from '~/queries/schema/schema-general'
import { isInsightVizNode } from '~/queries/utils'
import { QueryBasedInsightModel } from '~/types'

const SUPPORTED_INSIGHT_TYPES: Partial<Record<NodeKind, CustomerJourneyInsightType>> = {
    [NodeKind.TrendsQuery]: 'TRENDS',
    [NodeKind.StickinessQuery]: 'STICKINESS',
    [NodeKind.LifecycleQuery]: 'LIFECYCLE',
    [NodeKind.FunnelsQuery]: 'FUNNELS',
    [NodeKind.RetentionQuery]: 'RETENTION',
    [NodeKind.PathsQuery]: 'PATHS',
}

export interface DashboardJourneyTileContext {
    tileId: number
    insightShortId: string
    insightType: CustomerJourneyInsightType | null
}

export interface DashboardJourneyRequiredTile extends Omit<DashboardJourneyTileContext, 'insightType'> {
    insightType: CustomerJourneyInsightType
}

export type DashboardJourneyTileManifestEntry = Pick<DashboardJourneyTileContext, 'tileId' | 'insightShortId'>

export interface DashboardJourneyRenderReadiness extends DashboardJourneyRequiredTile {
    attemptId: string
    expectedResult: unknown
}

export interface DashboardJourneySnapshot {
    attemptId: string
    requiredTiles: Record<number, DashboardJourneyRequiredTile>
}

export interface DashboardJourneyActivation extends DashboardJourneySnapshot {
    renderReadiness: DashboardJourneyRenderReadiness[]
}

interface ActiveDashboardJourney extends DashboardJourneySnapshot {
    handle: CustomerJourney
    kind: 'open' | 'refresh'
    startedAt: number
    excludedCount: number
    ready: Record<number, number>
    failed: Record<number, true>
}

interface InitialDashboardJourney {
    attemptId: string
    handle: CustomerJourney
    startedAt: number
    manifest: readonly DashboardJourneyTileManifestEntry[] | null
    refreshTileIds: Set<number>
    currentResultsByTileId: Record<number, unknown>
    bufferedResults: Map<number, unknown>
    bufferedFailures: Map<number, DashboardJourneyErrorType>
}

type DashboardJourneyErrorType = NonNullable<CustomerJourneySummary['error_type']>

export function getDashboardJourneyInsightType(
    insight: Pick<QueryBasedInsightModel, 'query'>
): CustomerJourneyInsightType | null {
    if (!isInsightVizNode(insight.query)) {
        return null
    }
    return SUPPORTED_INSIGHT_TYPES[insight.query.source.kind] ?? null
}

export function isDashboardJourneyResultCommitted(actualResult: unknown, expectedResult: unknown): boolean {
    return expectedResult !== null && expectedResult !== undefined && Object.is(actualResult, expectedResult)
}

export class DashboardRefreshJourneyController {
    private visibleTiles = new Map<number, DashboardJourneyTileContext>()
    private observedTileIds = new Set<number>()
    private initial: InitialDashboardJourney | null = null
    private active: ActiveDashboardJourney | null = null

    public setTileVisibility(tile: DashboardJourneyTileContext, visible: boolean): DashboardJourneyActivation | null {
        this.observedTileIds.add(tile.tileId)
        if (visible) {
            this.visibleTiles.set(tile.tileId, tile)
        } else {
            this.visibleTiles.delete(tile.tileId)
        }
        return this.activateInitialIfObserved()
    }

    public beginInitialLoad(dashboardId: number, loadId: string): void {
        this.dispose('superseded')
        const handle = startCustomerJourney({
            journey_name: 'dashboard_open',
            resource_type: 'dashboard',
            resource_id: dashboardId,
            trigger: 'initial_load',
            readiness_contract_version: 1,
            readiness_scope: 'visible_product_analytics_tiles',
            attempt_id: loadId,
        })
        this.initial = handle
            ? {
                  attemptId: loadId,
                  handle,
                  startedAt: performance.now(),
                  manifest: null,
                  refreshTileIds: new Set(),
                  currentResultsByTileId: {},
                  bufferedResults: new Map(),
                  bufferedFailures: new Map(),
              }
            : null
    }

    public planInitialLoad(
        loadId: string,
        manifest: readonly DashboardJourneyTileManifestEntry[],
        refreshTileIds: readonly number[],
        currentResultsByTileId: Record<number, unknown>
    ): DashboardJourneyActivation | null {
        if (!this.initial || this.initial.attemptId !== loadId) {
            return null
        }
        this.initial.manifest = manifest
        this.initial.refreshTileIds = new Set(refreshTileIds)
        this.initial.currentResultsByTileId = currentResultsByTileId
        return this.activateInitialIfObserved()
    }

    public start(
        dashboardId: number,
        refreshId: string,
        dashboardTiles: readonly DashboardJourneyTileManifestEntry[],
        trigger: 'manual_refresh' | 'automatic_refresh' = 'manual_refresh'
    ): DashboardJourneySnapshot | null {
        this.dispose('superseded')

        const visible = [...this.visibleTiles.values()]
        // The manifest must contain every insight tile, including offscreen tiles. A saved insight duplicated
        // anywhere on the dashboard shares product state by short ID, so none of its visible copies are eligible.
        const insightOccurrences = new Map<string, number>()
        for (const tile of dashboardTiles) {
            insightOccurrences.set(tile.insightShortId, (insightOccurrences.get(tile.insightShortId) ?? 0) + 1)
        }
        const required = visible.filter(
            (tile): tile is DashboardJourneyRequiredTile =>
                tile.insightType !== null && insightOccurrences.get(tile.insightShortId) === 1
        )
        if (required.length === 0) {
            return null
        }

        const handle = startCustomerJourney({
            journey_name: 'dashboard_refresh',
            resource_type: 'dashboard',
            resource_id: dashboardId,
            trigger,
            readiness_contract_version: 1,
            readiness_scope: 'visible_product_analytics_tiles',
            attempt_id: refreshId,
        })
        if (!handle) {
            return null
        }

        const requiredTiles = Object.fromEntries(required.map((tile) => [tile.tileId, tile]))
        this.active = {
            attemptId: handle.attemptId,
            handle,
            kind: 'refresh',
            requiredTiles,
            excludedCount: visible.length - required.length,
            startedAt: performance.now(),
            ready: {},
            failed: {},
        }
        return { attemptId: handle.attemptId, requiredTiles }
    }

    public dataReady(
        attemptId: string,
        tileId: number,
        expectedResult: unknown
    ): DashboardJourneyRenderReadiness | null {
        if (this.initial && this.initial.attemptId === attemptId) {
            if (expectedResult !== null && expectedResult !== undefined) {
                this.initial.bufferedResults.set(tileId, expectedResult)
            }
            return null
        }
        const active = this.active
        const tile = active?.attemptId === attemptId ? active.requiredTiles[tileId] : undefined
        if (!active || !tile || expectedResult === null || expectedResult === undefined) {
            return null
        }
        return { ...tile, attemptId, expectedResult }
    }

    public renderCommitted(attemptId: string, tileId: number): boolean {
        const active = this.active
        const tile = active?.attemptId === attemptId ? active.requiredTiles[tileId] : undefined
        if (!active || !tile || active.failed[tileId] || active.ready[tileId] !== undefined) {
            return false
        }

        active.ready[tileId] = Math.max(0, Math.round(performance.now() - active.startedAt))
        if (Object.keys(active.ready).length === 1) {
            active.handle.firstUseful()
        }
        if (Object.keys(active.ready).length === Object.keys(active.requiredTiles).length) {
            active.handle.finish('usable', this.summary(active))
            this.active = null
        }
        return true
    }

    public failed(attemptId: string, tileId: number, errorType: DashboardJourneyErrorType): boolean {
        if (this.initial?.attemptId === attemptId) {
            this.initial.bufferedFailures.set(tileId, errorType)
            return false
        }
        const active = this.active
        if (!active || active.attemptId !== attemptId || !active.requiredTiles[tileId]) {
            return false
        }
        active.failed[tileId] = true
        active.handle.finish('failed', { ...this.summary(active), error_type: errorType })
        this.active = null
        return true
    }

    public failLoad(attemptId: string, errorType: DashboardJourneyErrorType): void {
        if (this.initial?.attemptId === attemptId) {
            this.initial.handle.finish('failed', { error_type: errorType })
            this.initial = null
            return
        }
        if (this.active && this.active.attemptId === attemptId) {
            this.active.handle.finish('failed', { ...this.summary(this.active), error_type: errorType })
            this.active = null
        }
    }

    public dispose(reason: CustomerJourneyEndReason): void {
        if (this.initial) {
            const initialReason = reason === 'observation_stopped' ? 'exited' : reason
            this.initial.handle.finish(initialReason, { end_reason: initialReason })
            this.initial = null
        }
        if (this.active) {
            const activeReason = this.active.kind === 'open' && reason === 'observation_stopped' ? 'exited' : reason
            this.active.handle.finish(activeReason, { ...this.summary(this.active), end_reason: activeReason })
            this.active = null
        }
    }

    public get activeAttemptId(): string | null {
        return this.initial?.attemptId ?? this.active?.attemptId ?? null
    }

    private activateInitialIfObserved(): DashboardJourneyActivation | null {
        const initial = this.initial
        if (!initial?.manifest || !initial.manifest.every(({ tileId }) => this.observedTileIds.has(tileId))) {
            return null
        }

        const insightOccurrences = new Map<string, number>()
        for (const tile of initial.manifest) {
            insightOccurrences.set(tile.insightShortId, (insightOccurrences.get(tile.insightShortId) ?? 0) + 1)
        }
        const manifestTileIds = new Set(initial.manifest.map(({ tileId }) => tileId))
        const visible = [...this.visibleTiles.values()].filter(({ tileId }) => manifestTileIds.has(tileId))
        const required = visible.filter(
            (tile): tile is DashboardJourneyRequiredTile =>
                tile.insightType !== null && insightOccurrences.get(tile.insightShortId) === 1
        )
        const requiredTiles = Object.fromEntries(required.map((tile) => [tile.tileId, tile]))
        const active: ActiveDashboardJourney = {
            attemptId: initial.attemptId,
            handle: initial.handle,
            kind: 'open',
            requiredTiles,
            excludedCount: visible.length - required.length,
            startedAt: initial.startedAt,
            ready: {},
            failed: {},
        }
        this.initial = null

        if (required.length === 0) {
            active.handle.finish('observation_stopped', {
                ...this.summary(active),
                end_reason: 'observation_stopped',
            })
            return null
        }

        this.active = active
        for (const tile of required) {
            const errorType = initial.bufferedFailures.get(tile.tileId)
            if (errorType) {
                active.failed[tile.tileId] = true
                active.handle.finish('failed', { ...this.summary(active), error_type: errorType })
                this.active = null
                return null
            }
            if (!initial.refreshTileIds.has(tile.tileId)) {
                const currentResult = initial.currentResultsByTileId[tile.tileId]
                if (currentResult === null || currentResult === undefined) {
                    active.failed[tile.tileId] = true
                    active.handle.finish('failed', { ...this.summary(active), error_type: 'load_error' })
                    this.active = null
                    return null
                }
            }
        }

        const renderReadiness = required.flatMap((tile) => {
            const expectedResult = initial.refreshTileIds.has(tile.tileId)
                ? initial.bufferedResults.get(tile.tileId)
                : initial.currentResultsByTileId[tile.tileId]
            return expectedResult === null || expectedResult === undefined
                ? []
                : [{ ...tile, attemptId: initial.attemptId, expectedResult }]
        })
        return { attemptId: initial.attemptId, requiredTiles, renderReadiness }
    }

    private summary(active: ActiveDashboardJourney): CustomerJourneySummary {
        const tiles = Object.values(active.requiredTiles).sort((a, b) => a.tileId - b.tileId)
        const insight_type_summary: NonNullable<CustomerJourneySummary['insight_type_summary']> = {}
        for (const tile of tiles) {
            const current = insight_type_summary[tile.insightType] ?? {
                total_count: 0,
                ready_count: 0,
                failed_count: 0,
            }
            current.total_count++
            if (active.ready[tile.tileId] !== undefined) {
                current.ready_count++
                current.max_duration_ms = Math.max(current.max_duration_ms ?? 0, active.ready[tile.tileId])
            }
            if (active.failed[tile.tileId]) {
                current.failed_count++
            }
            insight_type_summary[tile.insightType] = current
        }
        const ready_count = Object.keys(active.ready).length
        const failed_count = Object.keys(active.failed).length
        const tile_results: CustomerJourneyTileResult[] = tiles
            .slice(0, CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT)
            .map((tile) => {
                const duration = active.ready[tile.tileId]
                if (duration !== undefined) {
                    return {
                        tile_id: tile.tileId,
                        insight_short_id: tile.insightShortId,
                        insight_type: tile.insightType,
                        state: 'ready',
                        duration_ms: duration,
                    }
                }
                return {
                    tile_id: tile.tileId,
                    insight_short_id: tile.insightShortId,
                    insight_type: tile.insightType,
                    state: active.failed[tile.tileId] ? 'failed' : 'pending',
                }
            })
        return {
            total_count: tiles.length,
            ready_count,
            failed_count,
            pending_count: tiles.length - ready_count - failed_count,
            excluded_count: active.excludedCount,
            insight_type_summary,
            tile_results,
            tile_results_truncated: tiles.length > CUSTOMER_JOURNEY_TILE_RESULTS_LIMIT,
        }
    }
}

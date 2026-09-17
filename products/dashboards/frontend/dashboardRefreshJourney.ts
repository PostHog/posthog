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

interface ActiveDashboardJourney extends DashboardJourneySnapshot {
    handle: CustomerJourney
    startedAt: number
    excludedCount: number
    ready: Record<number, number>
    failed: Record<number, true>
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
    private active: ActiveDashboardJourney | null = null

    public setTileVisibility(tile: DashboardJourneyTileContext, visible: boolean): void {
        if (visible) {
            this.visibleTiles.set(tile.tileId, tile)
        } else {
            this.visibleTiles.delete(tile.tileId)
        }
    }

    public start(
        dashboardId: number,
        refreshId: string,
        dashboardTiles: readonly DashboardJourneyTileManifestEntry[]
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
            trigger: 'manual_refresh',
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

    public failed(attemptId: string, tileId: number, errorType: DashboardJourneyErrorType): void {
        const active = this.active
        if (!active || active.attemptId !== attemptId || !active.requiredTiles[tileId]) {
            return
        }
        active.failed[tileId] = true
        active.handle.finish('failed', { ...this.summary(active), error_type: errorType })
        this.active = null
    }

    public dispose(reason: CustomerJourneyEndReason): void {
        if (this.active) {
            this.active.handle.finish(reason, { ...this.summary(this.active), end_reason: reason })
            this.active = null
        }
    }

    public get activeAttemptId(): string | null {
        return this.active?.attemptId ?? null
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

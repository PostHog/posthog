import api from 'lib/api'

import type { InsightModel } from '~/types'

export type TileUnavailableReason = 'no-access' | 'not-found' | 'failed'

export interface TileFetchResult {
    insight: InsightModel | null
    unavailable: TileUnavailableReason | null
}

/**
 * ClickHouse allows an organization six concurrent dashboard queries, and this dashboard puts no
 * cap on tiles, so the tiles queue here instead of arriving together and starving each other.
 */
const MAX_CONCURRENT_TILE_FETCHES = 4

let inFlight = 0
const waiting: (() => void)[] = []

async function acquireSlot(): Promise<void> {
    if (inFlight < MAX_CONCURRENT_TILE_FETCHES) {
        inFlight += 1
        return
    }
    await new Promise<void>((resolve) => waiting.push(resolve))
    inFlight += 1
}

function releaseSlot(): void {
    inFlight -= 1
    waiting.shift()?.()
}

/**
 * Fetch one tile's insight from its own project.
 *
 * The cross-project dashboard response carries ids only, so the tile is fetched here rather
 * than served with the dashboard. Going through the project's own insight endpoint is what
 * keeps the reader's access, the project's quota and the cache key correct: a reader without
 * access gets a 403 from that endpoint, and never receives the insight's name or query.
 */
export async function fetchCrossProjectTile(
    projectId: number,
    insightId: number,
    filtersOverride?: Record<string, unknown>
): Promise<TileFetchResult> {
    const params = new URLSearchParams({ refresh: 'blocking' })
    if (filtersOverride && Object.keys(filtersOverride).length > 0) {
        params.set('filters_override', JSON.stringify(filtersOverride))
    }

    await acquireSlot()
    try {
        const insight = await api.get(`api/projects/${projectId}/insights/${insightId}/?${params.toString()}`)
        return { insight, unavailable: null }
    } catch (error: any) {
        if (error?.status === 403) {
            return { insight: null, unavailable: 'no-access' }
        }
        if (error?.status === 404) {
            return { insight: null, unavailable: 'not-found' }
        }
        return { insight: null, unavailable: 'failed' }
    } finally {
        releaseSlot()
    }
}

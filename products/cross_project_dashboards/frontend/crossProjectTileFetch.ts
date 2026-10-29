import type { InsightModel } from '~/types'

import { insightsRetrieve } from 'products/product_analytics/frontend/generated/api'
import type { InsightsRetrieveParams } from 'products/product_analytics/frontend/generated/api.schemas'

import { crossProjectDashboardTracking } from './crossProjectDashboardTracking'

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

/** The project's own insight endpoint applies the reader's access, quota and cache key, so a reader without access gets a 403. */
export async function fetchCrossProjectTile(
    projectId: number,
    insightId: number,
    filtersOverride?: Record<string, unknown>
): Promise<TileFetchResult> {
    const params: InsightsRetrieveParams = { refresh: 'blocking' }
    if (filtersOverride && Object.keys(filtersOverride).length > 0) {
        params.filters_override = JSON.stringify(filtersOverride)
    }

    await acquireSlot()
    try {
        const insight = await insightsRetrieve(String(projectId), insightId, params)
        // InsightCard needs an InsightModel. The endpoint returns one, but its schema leaves out `saved`.
        return { insight: insight as unknown as InsightModel, unavailable: null }
    } catch (error: any) {
        const unavailable: TileUnavailableReason =
            error?.status === 403 ? 'no-access' : error?.status === 404 ? 'not-found' : 'failed'
        crossProjectDashboardTracking.tileUnavailable(unavailable)
        return { insight: null, unavailable }
    } finally {
        releaseSlot()
    }
}

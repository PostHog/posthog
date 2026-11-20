import { uuid } from 'lib/utils/dom'

import type { InsightModel } from '~/types'

import { insightsCancelCreate, insightsRetrieve } from 'products/product_analytics/frontend/generated/api'
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

/** Resolves false when the signal aborts first, so a cancelled refresh leaves the queue without running. */
async function acquireSlot(signal?: AbortSignal): Promise<boolean> {
    if (inFlight < MAX_CONCURRENT_TILE_FETCHES) {
        inFlight += 1
        return true
    }
    const granted = await new Promise<boolean>((resolve) => {
        const grant = (): void => {
            signal?.removeEventListener('abort', drop)
            resolve(true)
        }
        const drop = (): void => {
            waiting.splice(waiting.indexOf(grant), 1)
            resolve(false)
        }
        waiting.push(grant)
        signal?.addEventListener('abort', drop, { once: true })
    })
    if (granted) {
        inFlight += 1
    }
    return granted
}

function releaseSlot(): void {
    inFlight -= 1
    waiting.shift()?.()
}

function cancelServerQuery(projectId: number, clientQueryId: string): void {
    // The generated schema documents an insight as the body, but the endpoint reads only `client_query_id`.
    void insightsCancelCreate(String(projectId), { client_query_id: clientQueryId } as never).catch(() => {})
}

/**
 * The project's own insight endpoint applies the reader's access, quota and cache key, so a reader without access gets a 403.
 *
 * `blocking` answers from the cache while the cached result is still fresh, so only `refresh` recalculates.
 * Resolves to null when `signal` aborts the fetch.
 */
export async function fetchCrossProjectTile(
    projectId: number,
    insightId: number,
    filtersOverride?: Record<string, unknown>,
    { refresh = false, signal }: { refresh?: boolean; signal?: AbortSignal } = {}
): Promise<TileFetchResult | null> {
    const clientQueryId = uuid()
    // The endpoint also reads `client_query_id`, which its generated params type leaves out.
    const params: InsightsRetrieveParams & { client_query_id?: string } = {
        refresh: refresh ? 'force_blocking' : 'blocking',
        client_query_id: clientQueryId,
    }
    if (filtersOverride && Object.keys(filtersOverride).length > 0) {
        params.filters_override = JSON.stringify(filtersOverride)
    }

    if (!(await acquireSlot(signal))) {
        return null
    }
    try {
        const insight = await insightsRetrieve(String(projectId), insightId, params, { signal })
        // InsightCard needs an InsightModel. The endpoint returns one, but its schema leaves out `saved`.
        return { insight: insight as unknown as InsightModel, unavailable: null }
    } catch (error: any) {
        if (signal?.aborted) {
            cancelServerQuery(projectId, clientQueryId)
            return null
        }
        const unavailable: TileUnavailableReason =
            error?.status === 403 ? 'no-access' : error?.status === 404 ? 'not-found' : 'failed'
        crossProjectDashboardTracking.tileUnavailable(unavailable)
        return { insight: null, unavailable }
    } finally {
        releaseSlot()
    }
}

import api from 'lib/api'
import { requestIdFromHeaders } from 'lib/api-error'

import { getDashboardsStreamQueryResultsRetrieveUrl } from './generated/api'
import type {
    DashboardQuerySharingEventApi,
    DashboardSharingDebugApi,
    DashboardTileApi,
    DashboardsStreamQueryResultsRetrieveParams,
} from './generated/api.schemas'

export interface DashboardStreamResultTiming {
    requestToResultMs: number
    httpRequestId: string | null
}

export async function streamDashboardQueryResults(
    projectId: number,
    dashboardId: number,
    params: DashboardsStreamQueryResultsRetrieveParams,
    signal: AbortSignal,
    onTile: (
        tile: DashboardTileApi,
        debug: DashboardSharingDebugApi | undefined,
        timing: DashboardStreamResultTiming
    ) => void,
    onCached?: (
        cached: Required<Pick<DashboardQuerySharingEventApi, 'tiles' | 'pending'>>,
        timing: DashboardStreamResultTiming
    ) => void
): Promise<void> {
    let complete = false
    let httpRequestId: string | null = null
    const requestStartedAt = performance.now()
    // nosemgrep: prefer-codegen-api -- SSE transport has no generated client; the URL comes from the generated getDashboardsStreamQueryResultsRetrieveUrl.
    await api.stream(getDashboardsStreamQueryResultsRetrieveUrl(String(projectId), dashboardId, params), {
        signal,
        onOpen(response) {
            httpRequestId = requestIdFromHeaders(response.headers)
        },
        onMessage(event) {
            // Sample before processing the event so cached tiles in one delivery share the same arrival time.
            const timing = { requestToResultMs: performance.now() - requestStartedAt, httpRequestId }
            const data = JSON.parse(event.data)
            if (data.type === 'complete') {
                complete = true
            } else if (data.type === 'cached' && Array.isArray(data.tiles) && Array.isArray(data.pending)) {
                onCached?.(data, timing)
            } else if (data.type === 'tile' && typeof data.tile?.id === 'number') {
                onTile(data.tile, data.debug, timing)
            } else if (data.type === 'error') {
                throw new Error('Dashboard query stream failed')
            }
        },
        onError(error) {
            // Retrying the stream could recompute tiles already delivered; the caller retries only missing tiles.
            throw error
        },
    })
    if (!signal.aborted && !complete) {
        throw new Error('Dashboard query stream ended before completion')
    }
}

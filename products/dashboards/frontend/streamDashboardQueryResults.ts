import api from 'lib/api'

import { getDashboardsStreamQueryResultsRetrieveUrl } from './generated/api'
import type { DashboardTileApi, DashboardsStreamQueryResultsRetrieveParams } from './generated/api.schemas'

export async function streamDashboardQueryResults(
    projectId: number,
    dashboardId: number,
    params: DashboardsStreamQueryResultsRetrieveParams,
    signal: AbortSignal,
    onTile: (tile: DashboardTileApi) => void
): Promise<void> {
    let complete = false
    await api.stream(getDashboardsStreamQueryResultsRetrieveUrl(String(projectId), dashboardId, params), {
        signal,
        onMessage(event) {
            const data = JSON.parse(event.data)
            if (data.type === 'complete') {
                complete = true
            } else if (data.type === 'tile' && typeof data.tile?.id === 'number') {
                onTile(data.tile)
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

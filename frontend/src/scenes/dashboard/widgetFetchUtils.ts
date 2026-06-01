import { dashboardsRunWidgetsRetrieve } from '@posthog/products-dashboards/frontend/generated/api'
import type { DashboardWidgetRunResultApi } from '@posthog/products-dashboards/frontend/generated/api.schemas'

import type { DashboardTile, QueryBasedInsightModel } from '~/types'

export const WIDGET_CLIENT_TTL_MS = 15 * 60 * 1000

export function findNewlyAddedWidgetTiles(
    previousTileIds: ReadonlySet<number>,
    tiles: DashboardTile<QueryBasedInsightModel>[] | undefined | null
): DashboardTile<QueryBasedInsightModel>[] {
    if (!tiles?.length) {
        return []
    }

    return tiles.filter((tile) => !!tile.widget && !tile.deleted && !previousTileIds.has(tile.id))
}

export function chunkTileIds(tileIds: number[], chunkSize = 4): number[][] {
    const chunks: number[][] = []
    for (let i = 0; i < tileIds.length; i += chunkSize) {
        chunks.push(tileIds.slice(i, i + chunkSize))
    }
    return chunks
}

export type FetchRunWidgetsOptions = {
    signal?: AbortSignal
}

export async function fetchRunWidgets(
    projectId: string,
    dashboardId: number,
    tileIds: number[],
    options?: FetchRunWidgetsOptions
): Promise<DashboardWidgetRunResultApi[]> {
    if (tileIds.length === 0) {
        return []
    }

    const response = await dashboardsRunWidgetsRetrieve(
        projectId,
        dashboardId,
        { tile_ids: tileIds.join(',') },
        { signal: options?.signal }
    )

    return response.results
}

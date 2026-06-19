import { WIDGET_TILE_REFRESH_DEBOUNCE_MS } from '@posthog/products-dashboards/frontend/widgets/constants'

export type DashboardWidgetTileRefreshScheduler = {
    schedule: (tileId: number) => void
    cancelAll: () => void
}

export function createDashboardWidgetTileRefreshScheduler(
    refreshTile: (tileId: number) => void,
    debounceMs: number = WIDGET_TILE_REFRESH_DEBOUNCE_MS
): DashboardWidgetTileRefreshScheduler {
    const timeouts = new Map<number, ReturnType<typeof setTimeout>>()

    return {
        schedule(tileId: number): void {
            const existing = timeouts.get(tileId)
            if (existing) {
                clearTimeout(existing)
            }
            timeouts.set(
                tileId,
                setTimeout(() => {
                    timeouts.delete(tileId)
                    refreshTile(tileId)
                }, debounceMs)
            )
        },
        cancelAll(): void {
            for (const timeout of timeouts.values()) {
                clearTimeout(timeout)
            }
            timeouts.clear()
        },
    }
}

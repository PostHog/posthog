import type { Dashboard } from '../dashboard/dashboardTypes'

export type TileSpacing = 'tight' | 'compact' | 'standard'

export const TILE_SPACINGS: Record<TileSpacing, { label: string; gapPx: number }> = {
    tight: { label: 'Tight', gapPx: 8 },
    compact: { label: 'Compact', gapPx: 12 },
    standard: { label: 'Standard', gapPx: 16 },
}

export interface DashboardAppearance {
    tileSpacing?: TileSpacing
}

export function gapPxOf(dashboard: Dashboard): number {
    return TILE_SPACINGS[dashboard.appearance?.tileSpacing ?? 'compact'].gapPx
}

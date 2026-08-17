import { cloneLayoutItem, getAllCollisions, horizontalCompactor, verticalCompactor } from 'react-grid-layout'
import type { Compactor, Layout } from 'react-grid-layout'

import type { DashboardGridCompaction, DashboardTileSpacing } from '~/types'

export const DASHBOARD_TILE_SPACING_GAPS: Record<DashboardTileSpacing, number> = {
    tight: 8,
    condensed: 12,
    standard: 16,
    relaxed: 32,
    wide: 48,
}

export const DASHBOARD_TILE_SPACING_LABELS: Record<DashboardTileSpacing, string> = {
    tight: 'Tight',
    condensed: 'Compact',
    standard: 'Standard',
    relaxed: 'Relaxed',
    wide: 'Wide',
}

export const DASHBOARD_GRID_COMPACTION_LABELS: Record<DashboardGridCompaction, string> = {
    vertical: 'Fill empty space above',
    horizontal: 'Make room in the row',
    stable: 'Keep positions where possible',
}

export const preservePositionsCompactor: Compactor = {
    type: null,
    allowOverlap: false,
    compact: (layout: Layout): Layout => {
        const items = layout.map((item) => cloneLayoutItem(item))
        const placedItems = items.filter((item) => item.static)
        const movableItems = items.filter((item) => !item.static).sort((a, b) => a.y - b.y || a.x - b.x)

        for (const item of movableItems) {
            let collisions = getAllCollisions(placedItems, item)

            while (collisions.length > 0) {
                item.y = Math.max(...collisions.map((collision) => collision.y + collision.h))
                collisions = getAllCollisions(placedItems, item)
            }

            placedItems.push(item)
        }

        return items
    },
}

export function getDashboardTileSpacingGap(tileSpacing?: string): number {
    return DASHBOARD_TILE_SPACING_GAPS[tileSpacing as DashboardTileSpacing] ?? DASHBOARD_TILE_SPACING_GAPS.standard
}

export function getDashboardGridCompactor(layoutCompaction?: string): Compactor {
    switch (layoutCompaction) {
        case 'horizontal':
            return horizontalCompactor
        case 'stable':
            return preservePositionsCompactor
        default:
            return verticalCompactor
    }
}

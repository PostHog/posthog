import { horizontalCompactor, noCompactor, verticalCompactor } from 'react-grid-layout'
import type { Compactor } from 'react-grid-layout'

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
    none: 'Keep tile positions',
}

export function getDashboardTileSpacingGap(tileSpacing?: string): number {
    return DASHBOARD_TILE_SPACING_GAPS[tileSpacing as DashboardTileSpacing] ?? DASHBOARD_TILE_SPACING_GAPS.standard
}

export function getDashboardGridCompactor(layoutCompaction?: string): Compactor {
    switch (layoutCompaction) {
        case 'horizontal':
            return horizontalCompactor
        case 'none':
            return noCompactor
        default:
            return verticalCompactor
    }
}

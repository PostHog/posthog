import { cloneLayoutItem, horizontalCompactor, noCompactor } from 'react-grid-layout'
import type { Compactor, Layout, LayoutItem } from 'react-grid-layout'
import { fastVerticalCompactor } from 'react-grid-layout/extras'

import type { DashboardTileSpacing } from '~/types'

export const DashboardGridCompaction = {
    Vertical: 'vertical',
    Horizontal: 'horizontal',
    Stable: 'stable',
} as const

export type DashboardGridCompaction = (typeof DashboardGridCompaction)[keyof typeof DashboardGridCompaction]

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
    [DashboardGridCompaction.Vertical]: 'Stack tiles upward',
    [DashboardGridCompaction.Horizontal]: 'Stack tiles to the left',
    [DashboardGridCompaction.Stable]: 'Free-form placement',
}

type GridOccupancy = Map<number, Array<LayoutItem | undefined>>

const MAX_FREE_FORM_TILE_HEIGHT_ROWS = 100

function getOccupants(occupancy: GridOccupancy, item: LayoutItem, cols: number): LayoutItem[] {
    const occupants = new Set<LayoutItem>()
    const startX = Math.max(0, item.x)
    const endX = Math.min(cols, item.x + item.w)

    for (let y = item.y; y < item.y + item.h; y++) {
        const row = occupancy.get(y)
        for (let x = startX; row && x < endX; x++) {
            const occupant = row[x]
            if (occupant) {
                occupants.add(occupant)
            }
        }
    }

    return [...occupants]
}

function occupy(occupancy: GridOccupancy, item: LayoutItem, cols: number): void {
    const startX = Math.max(0, item.x)
    const endX = Math.min(cols, item.x + item.w)

    for (let y = item.y; y < item.y + item.h; y++) {
        const row = occupancy.get(y) ?? new Array<LayoutItem | undefined>(cols)
        for (let x = startX; x < endX; x++) {
            row[x] = item
        }
        occupancy.set(y, row)
    }
}

export const freePlacementCompactor: Compactor = noCompactor

export const makeRoomInRowCompactor: Compactor = horizontalCompactor

export interface DashboardGridCompactor extends Compactor {
    compactInteraction: (cols: number, activeTileId: string, restoredLayout: Layout, resizedLayout: Layout) => Layout
}

export function resolveFreePlacementCollisions(layout: Layout, cols: number, activeTileId?: string | null): Layout {
    const items = layout.map((item) => ({
        ...cloneLayoutItem(item),
        h: Math.min(item.h, MAX_FREE_FORM_TILE_HEIGHT_ROWS),
    }))
    const activeTile = activeTileId ? items.find((item) => item.i === activeTileId) : undefined
    const occupancy: GridOccupancy = new Map()
    for (const item of items) {
        if (item.static) {
            occupy(occupancy, item, cols)
        }
    }
    const movableItems = items.filter((item) => !item.static && item.i !== activeTileId)

    for (const item of activeTile && !activeTile.static ? [activeTile, ...movableItems] : movableItems) {
        let collisions = getOccupants(occupancy, item, cols)

        while (collisions.length > 0) {
            item.y = Math.max(...collisions.map((collision) => collision.y + collision.h))
            collisions = getOccupants(occupancy, item, cols)
        }

        occupy(occupancy, item, cols)
    }

    return items
}

export function getDashboardTileSpacingGap(tileSpacing?: string): number {
    return DASHBOARD_TILE_SPACING_GAPS[tileSpacing as DashboardTileSpacing] ?? DASHBOARD_TILE_SPACING_GAPS.standard
}

export function getDashboardGridCompactor(layoutCompaction?: DashboardGridCompaction): DashboardGridCompactor {
    const selectedCompaction = layoutCompaction ?? DashboardGridCompaction.Vertical
    const compactor = (() => {
        switch (selectedCompaction) {
            case DashboardGridCompaction.Horizontal:
                return makeRoomInRowCompactor
            case DashboardGridCompaction.Stable:
                return freePlacementCompactor
            default:
                return fastVerticalCompactor
        }
    })()

    return {
        ...compactor,
        compactInteraction: (cols, activeTileId, restoredLayout, resizedLayout): Layout => {
            switch (selectedCompaction) {
                case DashboardGridCompaction.Stable:
                    return resolveFreePlacementCollisions(restoredLayout, cols, activeTileId)
                case DashboardGridCompaction.Vertical:
                    return compactor.compact(resizedLayout, cols)
                default:
                    return compactor.compact(restoredLayout, cols)
            }
        },
    }
}

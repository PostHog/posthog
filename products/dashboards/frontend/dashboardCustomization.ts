import { cloneLayoutItem } from 'react-grid-layout'
import type { Compactor, Layout, LayoutItem } from 'react-grid-layout'
import { fastVerticalCompactor } from 'react-grid-layout/extras'

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

type GridOccupancy = Map<number, Array<LayoutItem | undefined>>

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

function createOccupancy(items: Layout, cols: number): GridOccupancy {
    const occupancy: GridOccupancy = new Map()

    for (const item of items) {
        if (item.static) {
            occupy(occupancy, item, cols)
        }
    }

    return occupancy
}

export const preservePositionsCompactor: Compactor = {
    type: null,
    allowOverlap: false,
    preventCollision: true,
    compact: (layout: Layout, cols: number): Layout => {
        const items = layout.map((item) => cloneLayoutItem(item))
        const occupancy = createOccupancy(items, cols)
        const movableItems = items.filter((item) => !item.static).sort((a, b) => a.y - b.y || a.x - b.x)

        for (const item of movableItems) {
            let collisions = getOccupants(occupancy, item, cols)

            while (collisions.length > 0) {
                item.y = Math.max(...collisions.map((collision) => collision.y + collision.h))
                collisions = getOccupants(occupancy, item, cols)
            }

            occupy(occupancy, item, cols)
        }

        return items
    },
}

export const makeRoomInRowCompactor: Compactor = {
    type: 'horizontal',
    allowOverlap: false,
    compact: (layout: Layout, cols: number): Layout => {
        const items = layout.map((item) => cloneLayoutItem(item))
        const occupancy = createOccupancy(items, cols)
        const movableItems = items.filter((item) => !item.static).sort((a, b) => a.y - b.y || a.x - b.x)

        for (const item of movableItems) {
            if (item.x + item.w > cols) {
                const rowItems = getOccupants(occupancy, { ...item, x: 0, w: cols }, cols)
                item.x = 0
                item.y = Math.max(item.y + 1, ...rowItems.map((rowItem) => rowItem.y + rowItem.h))
            }

            let collisions = getOccupants(occupancy, item, cols)

            while (collisions.length > 0) {
                const nextX = Math.max(...collisions.map((collision) => collision.x + collision.w))

                if (nextX + item.w <= cols) {
                    item.x = nextX
                } else {
                    item.x = 0
                    item.y = Math.max(...collisions.map((collision) => collision.y + collision.h))
                }

                collisions = getOccupants(occupancy, item, cols)
            }

            occupy(occupancy, item, cols)
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
            return makeRoomInRowCompactor
        case 'stable':
            return preservePositionsCompactor
        default:
            return fastVerticalCompactor
    }
}

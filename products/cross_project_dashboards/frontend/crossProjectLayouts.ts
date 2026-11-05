import type { LayoutItem } from 'react-grid-layout'

import type { DashboardLayoutSize, TileLayout } from '~/types'

import type { CrossProjectDashboardTileApi } from './generated/api.schemas'

/** Same grid as single-project dashboards, so the two read as one product. */
export const GRID_BREAKPOINTS: Record<DashboardLayoutSize, number> = { sm: 768, xs: 0 }
export const GRID_COLUMN_COUNTS: Record<DashboardLayoutSize, number> = { sm: 12, xs: 1 }
export const GRID_ROW_HEIGHT = 80
export const GRID_MARGIN: [number, number] = [16, 16]

const DEFAULT_WIDTH: Record<DashboardLayoutSize, number> = { sm: 6, xs: 1 }
const DEFAULT_HEIGHT = 5

export type ResponsiveTileLayouts = Record<DashboardLayoutSize, LayoutItem[]>

const SIZES: DashboardLayoutSize[] = ['sm', 'xs']

const storedLayout = (tile: CrossProjectDashboardTileApi, size: DashboardLayoutSize): TileLayout | null => {
    const layouts = tile.layouts as Record<string, TileLayout> | undefined
    const layout = layouts?.[size]
    return layout && typeof layout.w === 'number' && typeof layout.h === 'number' ? layout : null
}

/** Never written back, so a dashboard nobody arranged stays distinct from one arranged to look like the default. */
const defaultLayout = (index: number, size: DashboardLayoutSize): TileLayout => {
    const width = DEFAULT_WIDTH[size]
    const perRow = Math.max(1, Math.floor(GRID_COLUMN_COUNTS[size] / width))
    return {
        x: (index % perRow) * width,
        y: Math.floor(index / perRow) * DEFAULT_HEIGHT,
        w: width,
        h: DEFAULT_HEIGHT,
    }
}

export function layoutsForTiles(tiles: readonly CrossProjectDashboardTileApi[]): ResponsiveTileLayouts {
    return Object.fromEntries(
        SIZES.map((size) => [
            size,
            tiles.map((tile, index) => ({ ...(storedLayout(tile, size) ?? defaultLayout(index, size)), i: tile.id })),
        ])
    ) as ResponsiveTileLayouts
}

const samePosition = (a: TileLayout | null, b: TileLayout): boolean =>
    !!a && a.x === b.x && a.y === b.y && a.w === b.w && a.h === b.h

export interface TileLayoutUpdate {
    tileId: string
    layouts: Record<string, TileLayout>
}

/** The grid reports a change on mount and on every resize, so only a tile that differs from what is stored counts. */
export function changedTileLayouts(
    tiles: readonly CrossProjectDashboardTileApi[],
    next: Partial<ResponsiveTileLayouts>
): TileLayoutUpdate[] {
    const updates: TileLayoutUpdate[] = []

    for (const tile of tiles) {
        const layouts: Record<string, TileLayout> = {}
        let moved = false

        for (const size of SIZES) {
            const proposed = next[size]?.find((item) => item.i === tile.id)
            if (!proposed) {
                const kept = storedLayout(tile, size)
                if (kept) {
                    layouts[size] = { x: kept.x, y: kept.y, w: kept.w, h: kept.h }
                }
                continue
            }
            layouts[size] = { x: proposed.x, y: proposed.y, w: proposed.w, h: proposed.h }
            if (!samePosition(storedLayout(tile, size), proposed)) {
                moved = true
            }
        }

        if (moved) {
            updates.push({ tileId: tile.id, layouts })
        }
    }

    return updates
}

/** Compared against what the grid shows, defaults included, so an edit that moved nothing is no change. */
export function layoutsDiffer(saved: ResponsiveTileLayouts, next: Partial<ResponsiveTileLayouts> | null): boolean {
    if (!next) {
        return false
    }
    return SIZES.some((size) => {
        const shown = new Map(saved[size].map((item) => [item.i, item]))
        return (next[size] ?? []).some((item) => {
            const current = shown.get(item.i)
            return !current || !samePosition(current, item)
        })
    })
}

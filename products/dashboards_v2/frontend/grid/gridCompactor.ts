import type { Compactor, Layout } from 'react-grid-layout'

import { type Gesture, type PlacedItem, bottomOf, placeTiles } from './placeTiles'

/**
 * What the compactor reads from the grid while it runs. The grid library ignores a new layout while a tile is dragged,
 * so these are read through functions that return the grid's current values, not captured once.
 */
export interface GridCompactorState {
    /** The drag or resize running in this grid, or null. */
    gesture: () => Gesture | null
    /** Whether the dragged tile is over another grid, which this grid then closes up behind. */
    tileAway: () => boolean
    /** Heights of sections that are growing during the gesture, by tile id. */
    liveRows: () => Record<string, number>
    /** Called with how many rows the grid needs during a gesture. */
    onRows: (rows: number) => void
    /** Called with the place the dragged tile will land, to move the landing outline there. */
    onLanding: (place: PlacedItem | undefined) => void
}

/** Hands every placement to `placeTiles`, so the grid library never pushes tiles itself. */
export function createGridCompactor({ gesture, tileAway, liveRows, onRows, onLanding }: GridCompactorState): Compactor {
    return {
        type: 'vertical',
        allowOverlap: true,
        compact: (current: Layout, columns: number): Layout => {
            const active = gesture()
            if (!active) {
                return placeTiles(current as PlacedItem[], columns) as Layout
            }
            if (!tileAway()) {
                const placed = placeTiles(current as PlacedItem[], columns, active)
                onRows(bottomOf(placed))
                onLanding(placed.find((item) => item.i === active.activeId))
                return placed as Layout
            }
            // The tile is over another grid, so this one closes up without it, from where it was when the gesture began.
            const rows = liveRows()
            const rest = placeTiles(
                active.baseline
                    .filter((item) => item.i !== active.activeId)
                    .map((item) => ({ ...item, h: rows[item.i] ?? item.h })),
                columns
            )
            onRows(bottomOf(rest))
            const byId = new Map(rest.map((item) => [item.i, item]))
            return current.map((item) => ({ ...item, ...byId.get(item.i) }))
        },
    }
}

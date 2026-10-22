import { useCallback, useEffect, useRef, useState } from 'react'
import type { Layout, LayoutItem } from 'react-grid-layout'

import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import { getDropCell } from './dashboardTileSections'

/** Drop zone after the last group, for taking a tile out of its group. */
export const TAKE_OUT_DROP_ZONE_KEY = 'take-out-of-group'

interface TileGroupDragProps {
    enabled: boolean
    rowHeight: number
    margin: [number, number]
    layout: Layout
    moveTileToSection: (tileId: number, sectionKey: string | null, cell: { x: number; y: number } | null) => void
    restoreLayout: (layout: Layout) => void
}

interface TileGroupDrag {
    draggingTileId: string | null
    dropTargetKey: string | null
    frozenSourceGrid: { key: string; height: number } | null
    startTileDrag: (item: LayoutItem, element: HTMLElement | null) => void
    trackTileDrag: (event: Event) => void
    finishTileDrag: (item: LayoutItem | null, element: HTMLElement | null, event: Event) => void
}

/**
 * The band of `dashboardRoot` under the pointer, or null when the pointer has left that dashboard.
 * Undefined means the caller keeps the last band, because the pointer is in a gap between bands.
 */
function sectionKeyUnderPointer(event: Event, dashboardRoot: Element): string | null | undefined {
    const { clientX, clientY } = event as MouseEvent
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) {
        return undefined
    }
    const elements = document
        .elementsFromPoint(clientX, clientY)
        .filter((element) => !element.closest('.react-draggable-dragging'))
    for (const element of elements) {
        const section = element.closest('[data-dashboard-section]')
        if (section) {
            // A page can show several dashboards, and their bands share keys like `tiles-start`.
            return dashboardRoot.contains(section) ? section.getAttribute('data-dashboard-section') : null
        }
    }
    return elements.some((element) => dashboardRoot.contains(element)) ? undefined : null
}

/** Finds the band and grid cell under a dragged tile, so the logic can move the tile there on drop. */
export function useTileGroupDrag(props: TileGroupDragProps): TileGroupDrag {
    const latest = useRef(props)
    latest.current = props
    const [draggingTileId, setDraggingTileId] = useState<string | null>(null)
    const [dropTargetKey, setDropTargetKey] = useState<string | null>(null)
    // A dragged tile grows its own grid, which would push the bands below away from the pointer.
    const [frozenSourceGrid, setFrozenSourceGrid] = useState<{ key: string; height: number } | null>(null)
    const drag = useRef<{
        sourceKey: string
        keyUnderPointer: string | null
        dashboardRoot: Element
        layoutAtStart: Layout
    } | null>(null)

    const stopTracking = useCallback((): void => {
        drag.current = null
        setDropTargetKey(null)
        setDraggingTileId(null)
        setFrozenSourceGrid(null)
    }, [])

    // Escape leaves edit mode without react-grid-layout ending its drag, so a late drop must not move a tile.
    useEffect(() => {
        if (!props.enabled) {
            stopTracking()
        }
    }, [props.enabled, stopTracking])

    const startTileDrag = useCallback((item: LayoutItem, element: HTMLElement | null): void => {
        const section = element?.closest<HTMLElement>('[data-dashboard-section]')
        const dashboardRoot = element?.closest('.dashboard-items-wrapper')
        const sourceKey = section?.getAttribute('data-dashboard-section')
        if (!section || !dashboardRoot || !sourceKey) {
            return
        }
        drag.current = {
            sourceKey,
            keyUnderPointer: sourceKey,
            dashboardRoot,
            layoutAtStart: latest.current.layout,
        }
        const sourceGrid = section.querySelector<HTMLElement>('[data-dashboard-section-grid]')
        setFrozenSourceGrid(sourceGrid ? { key: sourceKey, height: sourceGrid.offsetHeight } : null)
        setDraggingTileId(item.i)
    }, [])

    const trackTileDrag = useCallback((event: Event): void => {
        const current = drag.current
        if (!current) {
            return
        }
        const keyUnderPointer = sectionKeyUnderPointer(event, current.dashboardRoot)
        if (keyUnderPointer !== undefined) {
            current.keyUnderPointer = keyUnderPointer
            setDropTargetKey(keyUnderPointer === current.sourceKey ? null : keyUnderPointer)
        }
    }, [])

    const finishTileDrag = useCallback(
        (item: LayoutItem | null, element: HTMLElement | null, event: Event): void => {
            const current = drag.current
            stopTracking()
            if (!current || !item || !latest.current.enabled) {
                return
            }
            // Autoscroll moves bands under a still pointer, so read the band at the drop point.
            const keyAtDrop = sectionKeyUnderPointer(event, current.dashboardRoot)
            const dropKey = keyAtDrop === undefined ? current.keyUnderPointer : keyAtDrop
            // The source grid reports its own layout right after drag stop, with the tile still in it.
            // Each change below waits for that report, so the report does not overwrite it.
            if (dropKey === null) {
                // The source grid has no lower edge, so it kept the tile at whatever row the drag reached.
                queueMicrotask(() => latest.current.restoreLayout(current.layoutAtStart))
                return
            }
            if (dropKey === current.sourceKey) {
                return
            }
            // A closed group shows no grid, so a drop there has no cell and goes to the bottom of the group.
            const grid = current.dashboardRoot.querySelector(`[data-dashboard-section-grid="${CSS.escape(dropKey)}"]`)
            const { rowHeight, margin } = latest.current
            const cell =
                grid && element
                    ? getDropCell({
                          tileRect: element.getBoundingClientRect(),
                          gridRect: grid.getBoundingClientRect(),
                          cols: BREAKPOINT_COLUMN_COUNTS.sm,
                          rowHeight,
                          margin,
                          tileWidth: item.w,
                      })
                    : null
            const sectionKey = dropKey === TAKE_OUT_DROP_ZONE_KEY ? null : dropKey
            queueMicrotask(() => latest.current.moveTileToSection(Number(item.i), sectionKey, cell))
        },
        [stopTracking]
    )

    return { draggingTileId, dropTargetKey, frozenSourceGrid, startTileDrag, trackTileDrag, finishTileDrag }
}

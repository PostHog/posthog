import { useCallback, useEffect, useRef, useState } from 'react'
import type { Layout, LayoutItem } from 'react-grid-layout'

import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import { type DashboardSection, getDropCell, isTileGroupSectionKey } from './dashboardTileSections'

export const TAKE_OUT_DROP_ZONE_KEY = 'take-out-of-group'

interface TileGroupDragProps {
    enabled: boolean
    sections: DashboardSection[]
    rowHeight: number
    margin: [number, number]
    layout: Layout | undefined
    moveTileToSection: (tileId: number, sectionKey: string | null, cell: { x: number; y: number } | null) => void
    restoreLayout: (layout: Layout) => void
}

interface TileGroupDrag {
    draggingTileId: string | null
    dropTargetKey: string | null
    frozenSourceGrid: { key: string; height: number } | null
    showTakeOutDropZone: boolean
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
        // The source grid's placeholder follows the pointer out of its band, so it must not count as that band.
        .filter((element) => !element.closest('.react-draggable-dragging, .react-grid-placeholder'))
    for (const element of elements) {
        const section = element.closest('[data-dashboard-section]')
        if (section) {
            // A page can show several dashboards, and their bands share keys like `tiles-start`.
            return dashboardRoot.contains(section) ? section.getAttribute('data-dashboard-section') : null
        }
    }
    return elements.some((element) => dashboardRoot.contains(element)) ? undefined : null
}

function dropKeyUnderPointer(
    event: Event,
    { dashboardRoot, sourceKey }: { dashboardRoot: Element; sourceKey: string }
): string | null | undefined {
    const key = sectionKeyUnderPointer(event, dashboardRoot)
    return key === TAKE_OUT_DROP_ZONE_KEY && !isTileGroupSectionKey(sourceKey) ? null : key
}

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
            layoutAtStart: latest.current.layout ?? [],
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
        const keyUnderPointer = dropKeyUnderPointer(event, current)
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
            const keyAtDrop = dropKeyUnderPointer(event, current)
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

    return {
        draggingTileId,
        dropTargetKey,
        frozenSourceGrid,
        showTakeOutDropZone: props.enabled && props.sections.at(-1)?.kind === 'group',
        startTileDrag,
        trackTileDrag,
        finishTileDrag,
    }
}

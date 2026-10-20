import { useCallback, useEffect, useRef, useState } from 'react'
import type { Layout, LayoutItem } from 'react-grid-layout'

import { BREAKPOINT_COLUMN_COUNTS } from 'scenes/dashboard/dashboardUtils'

import type { DashboardGridCompactor } from './dashboardCustomization'
import { type DashboardSection, getDropCell, moveTileToSection } from './dashboardTileSections'

/** Drop zone after the last group, for taking a tile out of its group. */
export const NEW_TILES_SECTION_KEY = 'new-tiles-section'
// Long enough that dragging past a closed group does not open it.
const OPEN_GROUP_AFTER_HOVER_MS = 700

interface TileGroupDragProps {
    sections: DashboardSection[]
    sectionLayouts: Layout[]
    collapsedTileGroupKeys: string[]
    compactor: DashboardGridCompactor
    rowHeight: number
    margin: [number, number]
    layout: Layout
    enabled: boolean
    toggleTileGroup: (groupKey: string) => void
    moveTileToGroup: (tileId: number, groupKey: string | null, layout: Layout) => void
    updateLayout: (layout: Layout) => void
}

interface TileGroupDrag {
    draggingTileId: string | null
    dropTargetKey: string | null
    frozenSourceGrid: { key: string; height: number } | null
    startTileDrag: (item: LayoutItem, element: HTMLElement | null) => void
    trackTileDrag: (event: Event) => void
    finishTileDrag: (item: LayoutItem | null, element: HTMLElement | null, event: Event) => void
}

const DASHBOARD_ROOT_SELECTOR = '.dashboard-items-wrapper'

/** The band of `dashboardRoot` under the pointer, or undefined when the event has no pointer position. */
function sectionKeyUnderPointer(event: Event, dashboardRoot: Element | null): string | null | undefined {
    const { clientX, clientY } = event as MouseEvent
    if (!Number.isFinite(clientX) || !Number.isFinite(clientY)) {
        return undefined
    }
    for (const element of document.elementsFromPoint(clientX, clientY)) {
        if (element.closest('.react-draggable-dragging')) {
            continue
        }
        const section = element.closest('[data-dashboard-section]')
        if (section) {
            // A page can show several dashboards, and their bands share keys like `tiles-start`.
            return !dashboardRoot || dashboardRoot.contains(section)
                ? section.getAttribute('data-dashboard-section')
                : null
        }
    }
    return null
}

/** Lets a dragged tile leave its band: it tracks the band under the pointer and moves the tile there on drop. */
export function useTileGroupDrag(props: TileGroupDragProps): TileGroupDrag {
    const latest = useRef(props)
    latest.current = props
    const [draggingTileId, setDraggingTileId] = useState<string | null>(null)
    const [dropTargetKey, setDropTargetKey] = useState<string | null>(null)
    // A dragged tile grows its own grid, which would push the bands below away from the pointer.
    const [frozenSourceGrid, setFrozenSourceGrid] = useState<{ key: string; height: number } | null>(null)
    const dropTargetRef = useRef<string | null>(null)
    const sourceKeyRef = useRef<string | null>(null)
    // The band under the pointer, the source band included, or null when the pointer is over no band.
    const keyUnderPointerRef = useRef<string | null>(null)
    const dashboardRootRef = useRef<Element | null>(null)
    const layoutAtStartRef = useRef<Layout>([])
    // Only a dashboard with bands tracks the pointer, so the plain single grid does no extra work while dragging.
    const trackingRef = useRef(false)
    const openTimer = useRef<number | null>(null)

    const clearOpenTimer = useCallback((): void => {
        if (openTimer.current) {
            window.clearTimeout(openTimer.current)
            openTimer.current = null
        }
    }, [])
    useEffect(() => clearOpenTimer, [clearOpenTimer])

    // Edit mode can turn off without react-grid-layout cancelling its drag (Escape discards edit mode,
    // and a source grid can remount under an unrelated state change). Stop tracking so a late
    // onDragStop/onStop does not move or re-save a tile once the dashboard is read-only again.
    useEffect(() => {
        if (props.enabled) {
            return
        }
        trackingRef.current = false
        clearOpenTimer()
        dropTargetRef.current = null
        setDropTargetKey(null)
        setDraggingTileId(null)
        setFrozenSourceGrid(null)
    }, [props.enabled, clearOpenTimer])

    const collapsedGroupKey = (sectionKey: string | null): string | null => {
        const section = latest.current.sections.find((candidate) => candidate.key === sectionKey)
        return section?.kind === 'group' && latest.current.collapsedTileGroupKeys.includes(section.groupKey)
            ? section.groupKey
            : null
    }

    const targetKey = (keyUnderPointer: string | null): string | null =>
        keyUnderPointer === sourceKeyRef.current ? null : keyUnderPointer

    const startTileDrag = useCallback((item: LayoutItem, element: HTMLElement | null): void => {
        trackingRef.current = latest.current.sections.length > 0
        if (!trackingRef.current) {
            return
        }
        const sourceKey =
            latest.current.sections.find((section) => section.tiles.some((tile) => tile.id.toString() === item.i))
                ?.key ?? null
        sourceKeyRef.current = sourceKey
        keyUnderPointerRef.current = sourceKey
        dashboardRootRef.current = element?.closest(DASHBOARD_ROOT_SELECTOR) ?? null
        layoutAtStartRef.current = latest.current.layout
        const sourceGrid = element?.closest<HTMLElement>('[data-dashboard-section-grid]')
        setFrozenSourceGrid(sourceKey && sourceGrid ? { key: sourceKey, height: sourceGrid.offsetHeight } : null)
        setDraggingTileId(item.i)
    }, [])

    const trackTileDrag = useCallback(
        (event: Event): void => {
            if (!trackingRef.current) {
                return
            }
            const keyUnderPointer = sectionKeyUnderPointer(event, dashboardRootRef.current)
            if (keyUnderPointer === undefined) {
                return
            }
            keyUnderPointerRef.current = keyUnderPointer
            const sectionKey = targetKey(keyUnderPointer)
            if (sectionKey === dropTargetRef.current) {
                return
            }
            dropTargetRef.current = sectionKey
            setDropTargetKey(sectionKey)
            clearOpenTimer()
            const groupKey = collapsedGroupKey(sectionKey)
            if (groupKey) {
                openTimer.current = window.setTimeout(() => {
                    if (collapsedGroupKey(dropTargetRef.current) === groupKey) {
                        latest.current.toggleTileGroup(groupKey)
                    }
                }, OPEN_GROUP_AFTER_HOVER_MS)
            }
        },
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- the helpers read the latest props and state through refs
        [clearOpenTimer]
    )

    const finishTileDrag = useCallback(
        (item: LayoutItem | null, element: HTMLElement | null, event: Event): void => {
            if (!trackingRef.current || !latest.current.enabled) {
                return
            }
            trackingRef.current = false
            // Autoscroll and the wheel move bands under a still pointer, so read the band at the drop point.
            const keyAtDrop = sectionKeyUnderPointer(event, dashboardRootRef.current)
            const keyUnderPointer = keyAtDrop === undefined ? keyUnderPointerRef.current : keyAtDrop
            const dropKey = targetKey(keyUnderPointer)
            clearOpenTimer()
            dropTargetRef.current = null
            setDropTargetKey(null)
            setDraggingTileId(null)
            setFrozenSourceGrid(null)

            const { sections, sectionLayouts, compactor, rowHeight, margin, moveTileToGroup, updateLayout } =
                latest.current
            const tileId = Number(item?.i)
            if (!item) {
                return
            }
            if (keyUnderPointer === null) {
                // The source grid has no lower edge, so it kept the tile at whatever row the drag reached.
                const layoutAtStart = layoutAtStartRef.current
                queueMicrotask(() => updateLayout(layoutAtStart))
                return
            }
            if (!dropKey) {
                return
            }
            const targetIndex =
                dropKey === NEW_TILES_SECTION_KEY
                    ? sections.length
                    : sections.findIndex((section) => section.key === dropKey)
            if (targetIndex < 0) {
                return
            }
            const grid = dashboardRootRef.current?.querySelector(
                `[data-dashboard-section-grid="${CSS.escape(dropKey)}"]`
            )
            const cell =
                grid && element && !collapsedGroupKey(dropKey)
                    ? getDropCell({
                          tileRect: element.getBoundingClientRect(),
                          gridRect: grid.getBoundingClientRect(),
                          cols: BREAKPOINT_COLUMN_COUNTS.sm,
                          rowHeight,
                          margin,
                          tileWidth: item.w,
                      })
                    : null
            const moved = moveTileToSection({
                sections,
                sectionLayouts,
                tileId,
                targetIndex,
                cell,
                compactor,
                cols: BREAKPOINT_COLUMN_COUNTS.sm,
            })
            // The source grid reports its own layout right after drag stop, with the tile still in it.
            // Commit the move after that report, so the report does not overwrite it.
            queueMicrotask(() => moveTileToGroup(tileId, moved.groupKey, moved.layout))
        },
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- the helpers read the latest props and state through refs
        [clearOpenTimer]
    )

    return { draggingTileId, dropTargetKey, frozenSourceGrid, startTileDrag, trackTileDrag, finishTileDrag }
}

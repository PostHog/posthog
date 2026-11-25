import 'react-grid-layout/css/styles.css'

import clsx from 'clsx'
import { type ReactNode, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { GridLayout } from 'react-grid-layout'
import type { Layout, LayoutItem } from 'react-grid-layout'

import { useDragAutoScroll } from 'scenes/dashboard/useDragAutoScroll'

import {
    GRID,
    type SizeOf,
    type Tile,
    type TilePlace,
    columnWidthPx,
    isSection,
    spanPx,
    widgetSize,
} from '../dashboard/dashboardTypes'
import { type DropTarget, type DropZones, gridUnderPointer, readDropZones } from './dropTargets'
import { createGridCompactor } from './gridCompactor'
import { useGridDrag } from './gridDrag'
import { contentRows, dropIntoGrid, toPlacedItems, withSectionRows } from './gridTiles'
import { type Gesture, type PlacedItem, bottomOf } from './placeTiles'
import { endResizeFeedback, resizeHandleOf, showResizeFeedback } from './resizeFeedback'
import { scrollParentOf } from './scrollParent'

const GHOST_ID = '__drop-preview'
const ALL_HANDLES: LayoutItem['resizeHandles'] = ['n', 'nw', 'ne', 'w', 'e', 's', 'sw', 'se']
const MARGIN: [number, number] = [GRID.gapPx, GRID.gapPx]
const NO_PADDING: [number, number] = [0, 0]
// A press inside a section's own grid belongs to the tile there, so the section must not start moving too.
const DRAG_CANCEL = '.DashboardV2__section-body, .DashboardV2__footer, button, a, input, textarea, [role="menuitem"]'

/** Reports the rows a section inside the grid takes while its own grid grows, or null when it stops. */
export type OnSectionRows = (id: string, rows: number | null) => void

export interface TileGridProps {
    gridId: string
    tiles: Tile[]
    cols: number
    width: number
    editable: boolean
    sizeOf: SizeOf
    /** Draws a cell. Keep it stable: a new function re-renders every tile on each drag move. */
    renderTile: (tile: Tile, columnPx: number, onSectionRows: OnSectionRows) => ReactNode
    /** Looks up a tile carried in from another grid, so this grid can preview where it lands. */
    findCarried: (id: string) => Tile | null
    onPlaceTiles: (places: Record<string, TilePlace>, resized?: string) => void
    /** Left out when the person may not move tiles between grids, so a tile only moves within its own. */
    onMoveTile?: (id: string, target: DropTarget) => void
    onLiveRows?: (rows: number | null) => void
}

function toLayout(tiles: Tile[], sizeOf: SizeOf): Layout {
    return toPlacedItems(tiles, sizeOf).map((item, index) => {
        const tile = tiles[index]
        // A closed section is one row, so it is resized in width only. An open one can be made taller than its tiles
        // need, but never shorter.
        if (isSection(tile)) {
            if (tile.widget.collapsed) {
                return { ...item, minH: item.h, maxH: item.h, resizeHandles: ['w', 'e'] }
            }
            return { ...item, minH: contentRows(tile.widget), maxH: undefined, resizeHandles: ALL_HANDLES }
        }
        return { ...item, minH: widgetSize(tile.widget, sizeOf).minH, maxH: undefined, resizeHandles: ALL_HANDLES }
    })
}

export function TileGrid({
    gridId,
    tiles,
    cols,
    width,
    editable,
    sizeOf,
    renderTile,
    findCarried,
    onPlaceTiles,
    onMoveTile,
    onLiveRows,
}: TileGridProps): JSX.Element {
    const { dropTarget, setDropTarget } = useGridDrag()
    const rootRef = useRef<HTMLDivElement>(null)
    const { startAutoScroll, autoScrollOnDrag, stopAutoScroll } = useDragAutoScroll(
        () => rootRef.current && scrollParentOf(rootRef.current)
    )
    const resizeHandle = useRef('')
    // The grid reports a resize only when the size changes, so a tile already at its minimum would never show it.
    // While a resize runs, every pointer move updates the feedback from the latest size.
    const resizeFeedback = useRef<{ tile: HTMLElement; item: LayoutItem; stop: () => void } | null>(null)
    const gesture = useRef<Gesture | null>(null)
    const lastTarget = useRef<DropTarget | null>(null)
    const dropZones = useRef<DropZones | null>(null)
    const lastRows = useRef<number | null>(null)
    const [liveSectionRows, setLiveSectionRows] = useState<Record<string, number>>({})
    const setSectionRows = useCallback((id: string, rows: number | null): void => {
        setLiveSectionRows((previous) => {
            if (rows === null) {
                const { [id]: _ended, ...rest } = previous
                return id in previous ? rest : previous
            }
            return previous[id] === rows ? previous : { ...previous, [id]: rows }
        })
    }, [])

    // A tile carried in from another grid. Only the grid under the pointer gets a value.
    const incoming: DropTarget | null = dropTarget?.grid === gridId ? dropTarget : null
    const shownTiles = useMemo(() => {
        const carried = incoming && findCarried(incoming.tileId)
        // The sections get their heights first, as the drop does, so the preview is where the tile will land.
        const sized = withSectionRows(tiles, cols, liveSectionRows, sizeOf)
        if (!incoming || !carried) {
            return sized
        }
        return dropIntoGrid(sized, cols, { ...carried, id: GHOST_ID }, incoming.x ?? 0, incoming.y ?? 0, sizeOf)
    }, [findCarried, tiles, cols, incoming, liveSectionRows, sizeOf])
    const layout = useMemo(
        () =>
            toLayout(shownTiles, sizeOf).map((item) =>
                liveSectionRows[item.i] ? { ...item, minH: 1, maxH: undefined } : item
            ),
        [shownTiles, liveSectionRows, sizeOf]
    )

    const reportRows = useCallback(
        (rows: number | null): void => {
            if (rows !== lastRows.current) {
                lastRows.current = rows
                onLiveRows?.(rows)
            }
        },
        [onLiveRows]
    )
    // A section growing inside this grid, or a tile hovering over it, changes how tall this grid is too.
    const growing = Object.keys(liveSectionRows).length > 0 || incoming !== null
    useLayoutEffect(() => {
        if (!gesture.current) {
            reportRows(growing ? bottomOf(layout) : null)
        }
    }, [layout, growing, reportRows])

    // The grid library draws the landing outline from the place the tile had one pointer move ago, so the outline
    // and the drop can differ by a cell when the pointer stops. This moves the outline to the place just worked
    // out, after the library has drawn its own and before the browser paints.
    const size = useRef({ width, cols })
    size.current = { width, cols }
    const showLanding = useCallback((place: PlacedItem | undefined): void => {
        requestAnimationFrame(() => {
            const outline = rootRef.current?.querySelector<HTMLElement>(
                ':scope > .react-grid-layout > .react-grid-placeholder'
            )
            if (!outline || !place) {
                return
            }
            const columnPx = columnWidthPx(size.current.width, size.current.cols)
            outline.style.transform = `translate(${place.x * (columnPx + GRID.gapPx)}px, ${place.y * (GRID.rowPx + GRID.gapPx)}px)`
            outline.style.width = `${spanPx(place.w, columnPx)}px`
            outline.style.height = `${spanPx(place.h, GRID.rowPx)}px`
        })
    }, [])

    // The grid library ignores a new layout while a tile is dragged, so the compactor reads these from a ref.
    const liveRows = useRef(liveSectionRows)
    liveRows.current = liveSectionRows

    const compactor = useMemo(
        () =>
            createGridCompactor({
                gesture: () => gesture.current,
                tileAway: () => lastTarget.current !== null,
                liveRows: () => liveRows.current,
                onRows: reportRows,
                onLanding: showLanding,
            }),
        [reportRows, showLanding]
    )

    const begin = useCallback((current: Layout, item: LayoutItem | null, kind: Gesture['kind']): void => {
        if (item) {
            gesture.current = { activeId: item.i, kind, baseline: current.map((other) => ({ ...other })) }
        }
    }, [])

    const setAway = useCallback(
        (target: DropTarget | null): void => {
            const previous = lastTarget.current
            if (previous?.grid === target?.grid && previous?.x === target?.x && previous?.y === target?.y) {
                return
            }
            lastTarget.current = target
            rootRef.current?.classList.toggle('DashboardV2__grid--tile-away', target !== null)
            setDropTarget(target)
        },
        [setDropTarget]
    )

    const savePlaces = useCallback(
        (finalLayout: Layout, resized?: string): void => {
            const places: Record<string, TilePlace> = {}
            for (const { i, x, y, w, h } of finalLayout) {
                places[i] = { x, y, w, h }
            }
            onPlaceTiles(places, resized)
        },
        [onPlaceTiles]
    )

    // A cell that mounts after the grid did is a tile just added, which can land below the scrolled view.
    const gridMounted = useRef(false)
    useEffect(() => {
        gridMounted.current = true
    }, [])
    const scrollToAdded = useCallback((marker: HTMLSpanElement | null): void => {
        if (marker && gridMounted.current) {
            const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
            marker.parentElement?.scrollIntoView({ block: 'nearest', behavior: reduceMotion ? 'auto' : 'smooth' })
        }
    }, [])

    // A grid can leave the page while a tile from it is still carried: undo, or its section closing.
    useEffect(
        () => () => {
            if (lastTarget.current) {
                setDropTarget(null)
            }
            onLiveRows?.(null)
            resizeFeedback.current?.stop()
        },
        // oxlint-disable-next-line react-hooks/exhaustive-deps -- runs once, when the grid leaves the page
        []
    )

    const end = useCallback((): void => {
        gesture.current = null
        stopAutoScroll()
        reportRows(null)
    }, [stopAutoScroll, reportRows])

    const children = useMemo(
        () =>
            shownTiles.map((tile) =>
                tile.id === GHOST_ID ? (
                    <div key={GHOST_ID} className="DashboardV2__drop-preview" />
                ) : (
                    <div key={tile.id} data-dv2-tile={tile.id} className="DashboardV2__tile">
                        {/* The grid library replaces a cell's own ref with its own, so a marker inside reports the mount. */}
                        <span ref={scrollToAdded} hidden />
                        {renderTile(tile, columnWidthPx(width, cols), setSectionRows)}
                    </div>
                )
            ),
        [shownTiles, width, cols, renderTile, setSectionRows, scrollToAdded]
    )

    return (
        <div
            ref={rootRef}
            data-dv2-grid={gridId}
            data-dv2-cols={cols}
            className={clsx('DashboardV2__grid', editable && 'DashboardV2__grid--editable')}
            // The width is worked out in pixels from the grid around this one, so no class can carry it.
            // oxlint-disable-next-line react/forbid-dom-props
            style={{ width }}
        >
            <GridLayout
                width={width}
                layout={layout}
                gridConfig={{ cols, rowHeight: GRID.rowPx, margin: MARGIN, containerPadding: NO_PADDING }}
                dragConfig={{ enabled: editable, handle: '.DashboardV2__handle', cancel: DRAG_CANCEL }}
                resizeConfig={{ enabled: editable }}
                compactor={compactor}
                onDragStart={(current, _old, item, _placeholder, _event, node) => {
                    begin(current, item, 'drag')
                    dropZones.current = node ? readDropZones(node) : null
                    startAutoScroll()
                }}
                onDrag={(_current, _old, item, _placeholder, event, node) => {
                    autoScrollOnDrag(event)
                    if (!onMoveTile || !item || !node || !gesture.current || !dropZones.current) {
                        return
                    }
                    const under = gridUnderPointer(event, node, dropZones.current)
                    if (under && under.grid !== gridId) {
                        setAway({ ...under, tileId: item.i })
                    } else {
                        setAway(null)
                    }
                }}
                onDragStop={(finalLayout, _old, item) => {
                    const target = lastTarget.current
                    setAway(null)
                    end()
                    if (target && item && onMoveTile) {
                        onMoveTile(item.i, target)
                    } else {
                        savePlaces(finalLayout)
                    }
                }}
                onResizeStart={(current, _old, item, _placeholder, event) => {
                    resizeHandle.current = resizeHandleOf(event)
                    begin(current, item, 'resize')
                    const tile =
                        item && rootRef.current?.querySelector<HTMLElement>(`[data-dv2-tile="${CSS.escape(item.i)}"]`)
                    if (item && tile) {
                        const onMove = (move: MouseEvent): void => {
                            const active = resizeFeedback.current
                            if (active) {
                                showResizeFeedback(active.tile, active.item, resizeHandle.current, move)
                            }
                        }
                        document.addEventListener('mousemove', onMove)
                        resizeFeedback.current = {
                            tile,
                            item,
                            stop: () => document.removeEventListener('mousemove', onMove),
                        }
                    }
                }}
                onResize={(_current, _old, item) => {
                    if (item && resizeFeedback.current) {
                        resizeFeedback.current.item = item
                    }
                }}
                onResizeStop={(finalLayout, _old, item) => {
                    resizeFeedback.current?.stop()
                    endResizeFeedback(resizeFeedback.current?.tile ?? null)
                    resizeFeedback.current = null
                    end()
                    savePlaces(finalLayout, item?.i)
                }}
            >
                {children}
            </GridLayout>
        </div>
    )
}

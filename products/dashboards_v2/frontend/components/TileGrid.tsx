import 'react-grid-layout/css/styles.css'

import clsx from 'clsx'
import { useActions, useSelector } from 'kea'
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { GridLayout } from 'react-grid-layout'
import type { Compactor, Layout, LayoutItem } from 'react-grid-layout'

import { useDragAutoScroll } from 'scenes/dashboard/useDragAutoScroll'

import { type DropTarget, dashboardV2Logic } from '../dashboardV2Logic'
import { dropIntoGrid, findTile, toPlacedItems, withSectionRows } from '../layout/dashboardEdits'
import { GRID, type Tile, type TilePlace, columnWidthPx, isSection, spanPx } from '../layout/dashboardTypes'
import { type DropZones, gridUnderPointer, readDropZones } from '../layout/dropTargets'
import { type Gesture, type PlacedItem, bottomOf, placeTiles } from '../layout/placeTiles'
import { widgetSize } from '../layout/widgetSizes'
import { TileFrame } from './TileFrame'

const GHOST_ID = '__drop-preview'
const MARGIN: [number, number] = [GRID.gapPx, GRID.gapPx]
const NO_PADDING: [number, number] = [0, 0]
// A press inside a section's own grid belongs to the tile there, so the section must not start moving too.
const DRAG_CANCEL = '.DashboardV2__section-body, button, a, input, textarea, [role="menuitem"]'

interface TileGridProps {
    gridId: string
    tiles: Tile[]
    cols: number
    width: number
    editable: boolean
    onLiveRows?: (rows: number | null) => void
}

function toLayout(tiles: Tile[]): Layout {
    return toPlacedItems(tiles).map((item, index) => {
        const tile = tiles[index]
        return {
            ...item,
            minH: isSection(tile) ? item.h : widgetSize(tile.widget).minH,
            maxH: isSection(tile) ? item.h : undefined,
            resizeHandles: isSection(tile) ? ['w', 'e'] : ['w', 'e', 's', 'sw', 'se'],
        }
    })
}

export function TileGrid({ gridId, tiles, cols, width, editable, onLiveRows }: TileGridProps): JSX.Element {
    const { applyDashboardEdit, setDropTarget } = useActions(dashboardV2Logic)
    const { startAutoScroll, autoScrollOnDrag, stopAutoScroll } = useDragAutoScroll()
    const rootRef = useRef<HTMLDivElement>(null)
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

    // A tile carried in from another grid. Only the grid under the pointer gets a value, so only it re-renders.
    const incoming: DropTarget | null = useSelector((state) => {
        const target = dashboardV2Logic.selectors.dropTarget(state)
        return target?.grid === gridId ? target : null
    })
    const shownTiles = useMemo(() => {
        const carried = incoming && findTile(dashboardV2Logic.values.dashboard, incoming.tileId)
        // The sections get their heights first, as the drop does, so the preview is where the tile will land.
        const sized = withSectionRows(tiles, cols, liveSectionRows)
        if (!incoming || !carried) {
            return sized
        }
        return dropIntoGrid(sized, cols, { ...carried, id: GHOST_ID }, incoming.x ?? 0, incoming.y ?? 0)
    }, [tiles, cols, incoming, liveSectionRows])
    const layout = useMemo(
        () =>
            toLayout(shownTiles).map((item) =>
                liveSectionRows[item.i] ? { ...item, minH: 1, maxH: undefined } : item
            ),
        [shownTiles, liveSectionRows]
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

    const compactor = useMemo<Compactor>(
        () => ({
            type: 'vertical',
            // The grid must not push tiles itself: `placeTiles` decides every place.
            allowOverlap: true,
            compact: (current: Layout, columns: number): Layout => {
                const active = gesture.current
                if (!active) {
                    return placeTiles(current as PlacedItem[], columns) as Layout
                }
                if (!lastTarget.current) {
                    const placed = placeTiles(current as PlacedItem[], columns, active)
                    reportRows(bottomOf(placed))
                    showLanding(placed.find((item) => item.i === active.activeId))
                    return placed as Layout
                }
                const rest = placeTiles(
                    active.baseline
                        .filter((item) => item.i !== active.activeId)
                        .map((item) => ({ ...item, h: liveRows.current[item.i] ?? item.h })),
                    columns
                )
                reportRows(bottomOf(rest))
                const byId = new Map(rest.map((item) => [item.i, item]))
                return current.map((item) => ({ ...item, ...byId.get(item.i) }))
            },
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
        (finalLayout: Layout): void => {
            const places: Record<string, TilePlace> = {}
            for (const { i, x, y, w, h } of finalLayout) {
                places[i] = { x, y, w, h }
            }
            applyDashboardEdit({ edit: 'placeTiles', grid: gridId, places })
        },
        [applyDashboardEdit, gridId]
    )

    // A grid can leave the page while a tile from it is still carried: undo, or its section closing.
    useEffect(
        () => () => {
            if (lastTarget.current) {
                setDropTarget(null)
            }
            onLiveRows?.(null)
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
                        <TileFrame
                            tile={tile}
                            columnPx={columnWidthPx(width, cols)}
                            editable={editable}
                            onSectionRows={setSectionRows}
                        />
                    </div>
                )
            ),
        [shownTiles, width, cols, editable, setSectionRows]
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
                    if (!item || !node || !gesture.current || !dropZones.current) {
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
                    if (target && item) {
                        applyDashboardEdit({
                            edit: 'moveTile',
                            id: item.i,
                            grid: target.grid,
                            x: target.x,
                            y: target.y,
                        })
                    } else {
                        savePlaces(finalLayout)
                    }
                }}
                onResizeStart={(current, _old, item) => begin(current, item, 'resize')}
                onResizeStop={(finalLayout) => {
                    end()
                    savePlaces(finalLayout)
                }}
            >
                {children}
            </GridLayout>
        </div>
    )
}

import clsx from 'clsx'
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Layout } from 'react-grid-layout'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { DEFAULT_INSERTED_TILE_SIZE } from 'scenes/dashboard/tileLayouts'

interface InsertTileOverlayProps {
    /** The current breakpoint's tile layout (sm) — used to find the gaps between rows. */
    layout: Layout | undefined
    gridWidth: number
    /** Grid column count (sm breakpoint). */
    cols: number
    rowHeight: number
    /** Horizontal grid margin (px) between columns. */
    marginX: number
    /** Vertical grid margin (px) — the gap between rows where the "+" affordance sits. */
    marginY: number
    canEditDashboard: boolean
    isMobileView: boolean
    /** Hide while a drag/resize gesture is in progress. */
    disabled?: boolean
    /** Builds the add-tile menu for an insertion at the given grid column + row. */
    getMenuItems: (targetX: number, targetY: number) => LemonMenuItem[]
}

/** A visible run of the boundary line (px), between the tiles a row cuts across. */
interface LineSegment {
    left: number
    width: number
}

/** A rendered tile's box in overlay-local px, used to clip the line so it passes behind cards. */
interface TileRect {
    top: number
    bottom: number
    left: number
    right: number
}

/**
 * Overlays thin hover strips in the gaps between dashboard grid rows. Hovering a strip reveals a
 * "+" that opens the same add-tile menu as the header — but the new tile is inserted at that row
 * rather than appended at the bottom. Shown to anyone with edit access, in both view and edit mode.
 */
export function InsertTileOverlay({
    layout,
    gridWidth,
    cols,
    rowHeight,
    marginX,
    marginY,
    canEditDashboard,
    isMobileView,
    disabled,
    getMenuItems,
}: InsertTileOverlayProps): JSX.Element | null {
    const containerRef = useRef<HTMLDivElement>(null)
    const [tileRects, setTileRects] = useState<TileRect[]>([])

    const active = canEditDashboard && !isMobileView && !disabled

    // Row boundaries: the top (0), the start of every tile, and the bottom of the grid. We offer a line
    // at any row that lines up with a tile edge — even one that runs through a taller tile in another
    // column — so insertion is available next to every row on the board, not just clean full-width cuts.
    const boundaryRows = useMemo(() => {
        const rows = new Set<number>([0])
        let maxBottom = 0
        for (const item of layout || []) {
            rows.add(item.y)
            maxBottom = Math.max(maxBottom, item.y + item.h)
        }
        rows.add(maxBottom)
        return Array.from(rows).sort((a, b) => a - b)
    }, [layout])

    const rowTopPx = useCallback(
        (targetY: number): number => Math.max(marginY / 2, targetY * (rowHeight + marginY) - marginY / 2),
        [rowHeight, marginY]
    )

    // Measure the rendered tile boxes so we can clip the line behind them. Reading the real DOM rects
    // (not grid coords) keeps the clip exact regardless of zoom, padding, or content sizing.
    useLayoutEffect(() => {
        if (!active) {
            return
        }
        const measure = (): void => {
            const container = containerRef.current
            const parent = container?.parentElement
            if (!container || !parent) {
                return
            }
            const base = container.getBoundingClientRect()
            const rects: TileRect[] = []
            parent.querySelectorAll('.react-grid-item').forEach((el) => {
                if (el.classList.contains('react-grid-placeholder')) {
                    return
                }
                const r = el.getBoundingClientRect()
                rects.push({
                    top: r.top - base.top,
                    bottom: r.bottom - base.top,
                    left: r.left - base.left,
                    right: r.right - base.left,
                })
            })
            setTileRects(rects)
        }
        measure()
        const observer = new ResizeObserver(measure)
        observer.observe(containerRef.current!.parentElement!)
        window.addEventListener('resize', measure)
        return () => {
            observer.disconnect()
            window.removeEventListener('resize', measure)
        }
    }, [active, layout, gridWidth, rowHeight, marginY])

    // For each boundary, the visible runs of the line: the full width minus any rendered tile the row's
    // pixel passes through. Drawing only in the gaps makes the line read as passing *behind* the cards
    // instead of slicing across them, while the hover strip + "+" still span the whole row.
    const segmentsByRow = useMemo(() => {
        const byRow = new Map<number, LineSegment[]>()
        for (const targetY of boundaryRows) {
            const top = rowTopPx(targetY)
            const covered = tileRects
                .filter((rect) => rect.top < top && rect.bottom > top)
                .map(
                    (rect) =>
                        [Math.max(0, rect.left - marginX / 2), Math.min(gridWidth, rect.right + marginX / 2)] as [
                            number,
                            number,
                        ]
                )
                .sort((a, b) => a[0] - b[0])

            const merged: Array<[number, number]> = []
            for (const interval of covered) {
                const last = merged[merged.length - 1]
                if (last && interval[0] <= last[1]) {
                    last[1] = Math.max(last[1], interval[1])
                } else {
                    merged.push([...interval])
                }
            }

            const segments: LineSegment[] = []
            let cursor = 0
            for (const [start, end] of merged) {
                if (start > cursor) {
                    segments.push({ left: cursor, width: start - cursor })
                }
                cursor = Math.max(cursor, end)
            }
            if (cursor < gridWidth) {
                segments.push({ left: cursor, width: gridWidth - cursor })
            }
            byRow.set(targetY, segments)
        }
        return byRow
    }, [boundaryRows, tileRects, gridWidth, marginX, rowTopPx])

    // Resolve which grid column the cursor (px from the grid's left edge) sits over at a given row, so
    // the inserted tile lands under the "+" rather than always full-left. Prefer the column of the tile
    // the cursor is over near the row; fall back to snapping the cursor to the nearest column.
    const resolveTargetX = useCallback(
        (targetY: number, pxX: number): number => {
            const colWidth = (gridWidth - marginX * (cols - 1)) / cols
            for (const item of layout || []) {
                const left = item.x * (colWidth + marginX)
                const right = left + item.w * colWidth + (item.w - 1) * marginX
                const touchesRow = item.y <= targetY && item.y + item.h >= targetY
                if (touchesRow && pxX >= left && pxX <= right) {
                    return item.x
                }
            }
            const snapped = Math.round(pxX / (colWidth + marginX))
            return Math.min(Math.max(snapped, 0), Math.max(0, cols - DEFAULT_INSERTED_TILE_SIZE.w))
        },
        [layout, gridWidth, cols, marginX]
    )

    if (!active) {
        return null
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div ref={containerRef} className="absolute inset-0 pointer-events-none" style={{ zIndex: 6 }}>
            {boundaryRows.map((targetY) => (
                <InsertionStrip
                    key={targetY}
                    targetY={targetY}
                    // Center the strip on the gap above the tiles that start at this row. The lower bound
                    // keeps the targetY=0 strip inside the top gap rather than clipped above the container.
                    topPx={rowTopPx(targetY)}
                    gridWidth={gridWidth}
                    segments={segmentsByRow.get(targetY) ?? [{ left: 0, width: gridWidth }]}
                    resolveTargetX={resolveTargetX}
                    getMenuItems={getMenuItems}
                />
            ))}
        </div>
    )
}

// Generous transparent hover zone so the thin line/"+" is easy to target (the visible bits stay
// centered on the row boundary). Larger than the inter-row gap, so it bleeds a little into the
// adjacent tiles — that's the intended trade-off for a comfortable hit area.
const HOVER_HIT_HEIGHT = 28
// Keep the "+" fully on the strip when the cursor is near either end.
const BUTTON_EDGE_PADDING = 16

function InsertionStrip({
    targetY,
    topPx,
    gridWidth,
    segments,
    resolveTargetX,
    getMenuItems,
}: {
    targetY: number
    topPx: number
    gridWidth: number
    segments: LineSegment[]
    resolveTargetX: (targetY: number, pxX: number) => number
    getMenuItems: (targetX: number, targetY: number) => LemonMenuItem[]
}): JSX.Element {
    const stripRef = useRef<HTMLDivElement>(null)
    const buttonRef = useRef<HTMLDivElement>(null)
    // Latest "+" position along the strip (px). Frozen with the button while the menu is open, so it
    // holds the column the user opened the menu over — that's the column we insert into.
    const lastXRef = useRef(BUTTON_EDGE_PADDING)
    // Freeze the follow while the pointer is pressed: a click emits tiny mousemoves between mousedown
    // and mouseup, and repositioning the button mid-press moves it out from under the stationary cursor
    // so mouseup lands elsewhere and the browser never fires `click` — that's the lost first click.
    const pointerDownRef = useRef(false)
    const [menuOpen, setMenuOpen] = useState(false)

    const revealClass = menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'

    // Move the "+" to follow the cursor by writing to the DOM directly — no setState, so the LemonMenu
    // subtree never re-renders during a hover/move. Frozen while pressed (see pointerDownRef) and while
    // the menu is open so it stays anchored under the popover.
    const followCursor = (clientX: number): void => {
        if (menuOpen || pointerDownRef.current || !buttonRef.current) {
            return
        }
        const rect = stripRef.current?.getBoundingClientRect()
        if (rect) {
            const x = Math.min(Math.max(clientX - rect.left, BUTTON_EDGE_PADDING), gridWidth - BUTTON_EDGE_PADDING)
            lastXRef.current = x
            // Our Tailwind config sets `important: true`, so the `left-4` class is `left !important` and
            // would beat a plain inline `left`. Write with priority so the follow position actually wins.
            buttonRef.current.style.setProperty('left', `${x}px`, 'important')
        }
    }

    // Build items when the menu opens, resolving the column from the frozen "+" position. Stable
    // otherwise so the dropdown overlay isn't rebuilt under the pointer on unrelated re-renders.
    const menuItems = useMemo(
        () => getMenuItems(resolveTargetX(targetY, lastXRef.current), targetY),
        // menuOpen forces a rebuild on open so lastXRef (frozen there) picks the column under the cursor.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [getMenuItems, resolveTargetX, targetY, menuOpen]
    )

    return (
        <div
            ref={stripRef}
            className="group absolute pointer-events-auto"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: 0, width: gridWidth, top: topPx - HOVER_HIT_HEIGHT / 2, height: HOVER_HIT_HEIGHT }}
            onMouseEnter={(e) => followCursor(e.clientX)}
            onMouseMove={(e) => followCursor(e.clientX)}
            onMouseDown={() => (pointerDownRef.current = true)}
            onMouseUp={() => (pointerDownRef.current = false)}
            onMouseLeave={() => (pointerDownRef.current = false)}
        >
            {segments.map((segment, index) => (
                <div
                    key={index}
                    className={clsx(
                        'absolute top-1/2 -translate-y-1/2 h-0.5 bg-accent transition-opacity',
                        revealClass
                    )}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ left: segment.left, width: segment.width }}
                />
            ))}
            <div
                ref={buttonRef}
                // `left` is set imperatively in followCursor (not via the style prop) so the followed
                // position survives the open/close re-render and the menu stays anchored under the cursor.
                className={clsx(
                    'absolute left-4 top-1/2 -translate-x-1/2 -translate-y-1/2 transition-opacity',
                    revealClass
                )}
            >
                <LemonMenu items={menuItems} onVisibilityChange={setMenuOpen}>
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        icon={<IconPlusSmall />}
                        sideIcon={null}
                        data-attr="dashboard-inline-add-tile"
                    >
                        Add
                    </LemonButton>
                </LemonMenu>
            </div>
        </div>
    )
}

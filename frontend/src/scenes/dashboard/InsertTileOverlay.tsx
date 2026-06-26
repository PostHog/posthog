import clsx from 'clsx'
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Layout } from 'react-grid-layout'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { DEFAULT_INSERTED_TILE_SIZE } from 'scenes/dashboard/tileLayouts'

interface InsertTileOverlayProps {
    /** The current breakpoint's tile layout (sm) — a dependency that triggers re-measuring on change. */
    layout: Layout | undefined
    gridWidth: number
    /** Grid column count (sm breakpoint). */
    cols: number
    rowHeight: number
    /** Horizontal grid margin (px) between columns. */
    marginX: number
    /** Vertical grid margin (px) between rows. */
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

/** A rendered tile's box in overlay-local px, used to position and clip the line against real cards. */
interface TileRect {
    top: number
    bottom: number
    left: number
    right: number
}

/** A place to insert: the line's pixel Y, the grid row it maps to, and the gaps the line shows in. */
interface InsertBoundary {
    lineY: number
    gridRow: number
    segments: LineSegment[]
}

// The full width minus any rendered tile the line's pixel passes through. Drawing only in the gaps
// makes the line read as passing behind the cards instead of slicing across them.
function computeSegments(lineY: number, tileRects: TileRect[], gridWidth: number, marginX: number): LineSegment[] {
    const covered = tileRects
        .filter((rect) => rect.top < lineY && rect.bottom > lineY)
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
    return segments
}

/**
 * Overlays an insert affordance in the gaps between dashboard tiles. Hovering a gap reveals a line
 * (drawn behind the cards) and a "+" that opens the same add-tile menu as the header, inserting at
 * that column + row instead of appending. Positions come from the rendered tile boxes, so the line
 * sits exactly in the real gaps. Shown to anyone with edit access, in both view and edit mode.
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

    // Measure the rendered tile boxes; positioning and clipping both work off these so the line lands
    // in the real gaps regardless of zoom, padding, or grid-vs-render drift.
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
        const parent = containerRef.current!.parentElement!
        const resizeObserver = new ResizeObserver(measure)
        resizeObserver.observe(parent)
        // react-grid-layout repositions tiles via CSS transform without changing the container size, so
        // a ResizeObserver alone goes stale. Watch the grid's style/child mutations to re-measure on move.
        const gridEl = parent.querySelector('.react-grid-layout')
        const mutationObserver = new MutationObserver(measure)
        if (gridEl) {
            mutationObserver.observe(gridEl, {
                attributes: true,
                attributeFilter: ['style'],
                subtree: true,
                childList: true,
            })
        }
        window.addEventListener('resize', measure)
        return () => {
            resizeObserver.disconnect()
            mutationObserver.disconnect()
            window.removeEventListener('resize', measure)
        }
    }, [active, layout, gridWidth, rowHeight, marginY])

    // Insert boundaries derived from the rendered tiles: a line above each distinct tile-top (the gap
    // before it) plus one below the lowest tile. The very top edge is skipped — no inserting above the
    // board. Each line's grid row is recovered from its pixel position for the actual insert.
    const boundaries = useMemo((): InsertBoundary[] => {
        if (!tileRects.length) {
            return []
        }
        const unit = rowHeight + marginY
        const minTop = Math.min(...tileRects.map((r) => r.top))
        const maxBottom = Math.max(...tileRects.map((r) => r.bottom))

        // Distinct tile-top edges (rounded to merge tiles that share a row), excluding the first row.
        const edges = new Map<number, number>()
        for (const rect of tileRects) {
            if (rect.top - minTop < marginY) {
                continue
            }
            edges.set(Math.round(rect.top / 4) * 4, rect.top)
        }

        const result: InsertBoundary[] = []
        for (const edge of Array.from(edges.values()).sort((a, b) => a - b)) {
            const lineY = edge - marginY / 2
            result.push({
                lineY,
                gridRow: Math.round(edge / unit),
                segments: computeSegments(lineY, tileRects, gridWidth, marginX),
            })
        }
        // Append slot below the lowest tile.
        const bottomLineY = maxBottom + marginY / 2
        result.push({
            lineY: bottomLineY,
            gridRow: Math.round(maxBottom / unit),
            segments: computeSegments(bottomLineY, tileRects, gridWidth, marginX),
        })
        return result
    }, [tileRects, gridWidth, marginX, marginY, rowHeight])

    // Resolve which grid column the cursor sits over at a line, so the inserted tile lands under the
    // "+". Align to the column of the rendered tile bordering the gap; else snap to the nearest column.
    const resolveTargetX = useCallback(
        (lineY: number, pxX: number): number => {
            const colUnit = (gridWidth - marginX * (cols - 1)) / cols + marginX
            for (const rect of tileRects) {
                if (pxX < rect.left || pxX > rect.right) {
                    continue
                }
                const bordersGap = Math.abs(rect.top - lineY) <= marginY || Math.abs(rect.bottom - lineY) <= marginY
                if (bordersGap) {
                    return Math.round(rect.left / colUnit)
                }
            }
            const snapped = Math.round(pxX / colUnit)
            return Math.min(Math.max(snapped, 0), Math.max(0, cols - DEFAULT_INSERTED_TILE_SIZE.w))
        },
        [tileRects, gridWidth, cols, marginX, marginY]
    )

    if (!active) {
        return null
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div ref={containerRef} className="absolute inset-0 pointer-events-none" style={{ zIndex: 6 }}>
            {boundaries.map((boundary) => (
                <InsertionStrip
                    key={`${boundary.gridRow}:${Math.round(boundary.lineY)}`}
                    lineY={boundary.lineY}
                    gridRow={boundary.gridRow}
                    gridWidth={gridWidth}
                    segments={boundary.segments}
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
    lineY,
    gridRow,
    gridWidth,
    segments,
    resolveTargetX,
    getMenuItems,
}: {
    lineY: number
    gridRow: number
    gridWidth: number
    segments: LineSegment[]
    resolveTargetX: (lineY: number, pxX: number) => number
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
            // Hide the "+" when the cursor is over a tile (not in a gap) — inserting there would land the
            // affordance on top of a card. Only a real gap at the cursor is a valid insertion spot.
            const inGap = segments.some((segment) => x >= segment.left && x <= segment.left + segment.width)
            buttonRef.current.style.display = inGap ? '' : 'none'
            if (!inGap) {
                return
            }
            lastXRef.current = x
            // Our Tailwind config sets `important: true`, so the `left-4` class is `left !important` and
            // would beat a plain inline `left`. Write with priority so the follow position actually wins.
            buttonRef.current.style.setProperty('left', `${x}px`, 'important')
        }
    }

    // Build items when the menu opens, resolving the column from the frozen "+" position. Stable
    // otherwise so the dropdown overlay isn't rebuilt under the pointer on unrelated re-renders.
    const menuItems = useMemo(
        () => getMenuItems(resolveTargetX(lineY, lastXRef.current), gridRow),
        // menuOpen forces a rebuild on open so lastXRef (frozen there) picks the column under the cursor.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [getMenuItems, resolveTargetX, lineY, gridRow, menuOpen]
    )

    return (
        <div
            ref={stripRef}
            className="group absolute pointer-events-auto"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: 0, width: gridWidth, top: lineY - HOVER_HIT_HEIGHT / 2, height: HOVER_HIT_HEIGHT }}
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

import clsx from 'clsx'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Layout } from 'react-grid-layout'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'

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

/** A rendered tile's box in overlay-local px, used to position and gate the line against real cards. */
interface TileRect {
    top: number
    bottom: number
    left: number
    right: number
}

/**
 * A column span where dropping a tile actually lands it at the line: either above a tile whose top is
 * at the line (push that tile down) or below a tile whose bottom is at the line (append under it). Only
 * these spots are offered — anywhere else, vertical compaction would float the new tile above the line.
 */
interface InsertZone {
    left: number
    right: number
    targetX: number
    targetY: number
}

/** A place to insert: the line's pixel Y, the gaps the line shows in, and the valid drop zones. */
interface InsertBoundary {
    lineY: number
    segments: LineSegment[]
    zones: InsertZone[]
}

// The full width minus any rendered tile the line's pixel passes through, so the line reads as passing
// behind the cards instead of slicing across them.
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

// Drop zones for a line: a tile whose top sits on the line (insert above it, pushing it down) or whose
// bottom sits on the line (append directly below it). targetY comes from the measured px / row unit,
// which is exact since react-grid-layout positions tiles at row*unit. Deduped per column + row.
function computeZones(
    lineY: number,
    tileRects: TileRect[],
    unit: number,
    colUnit: number,
    marginY: number
): InsertZone[] {
    const seen = new Set<string>()
    const zones: InsertZone[] = []
    for (const rect of tileRects) {
        let targetY: number | null = null
        if (Math.abs(rect.top - lineY) <= marginY) {
            targetY = Math.round(rect.top / unit)
        } else if (Math.abs(rect.bottom - lineY) <= marginY) {
            targetY = Math.round(rect.bottom / unit)
        }
        if (targetY === null) {
            continue
        }
        const targetX = Math.round(rect.left / colUnit)
        const key = `${targetX}:${targetY}`
        if (seen.has(key)) {
            continue
        }
        seen.add(key)
        zones.push({ left: rect.left, right: rect.right, targetX, targetY })
    }
    return zones
}

/**
 * Overlays an insert affordance in the gaps between dashboard tiles. Hovering a gap reveals a line
 * (drawn behind the cards) and a "+" that opens the same add-tile menu as the header. Positions come
 * from the rendered tile boxes, and the "+" only appears over a tile that borders the line, so the new
 * tile always lands at the line (never floated above it by compaction). View and edit mode, edit access.
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

    // Measure the rendered tile boxes; positioning, clipping, and drop zones all work off these so the
    // line lands in the real gaps regardless of zoom, padding, or grid-vs-render drift.
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
    // board. Each line carries its drop zones so the "+" only shows where the tile lands at the line.
    const boundaries = useMemo((): InsertBoundary[] => {
        if (!tileRects.length) {
            return []
        }
        const unit = rowHeight + marginY
        const colUnit = (gridWidth - marginX * (cols - 1)) / cols + marginX
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

        const build = (lineY: number): InsertBoundary => ({
            lineY,
            segments: computeSegments(lineY, tileRects, gridWidth, marginX),
            zones: computeZones(lineY, tileRects, unit, colUnit, marginY),
        })

        const result = Array.from(edges.values())
            .sort((a, b) => a - b)
            .map((edge) => build(edge - marginY / 2))
        result.push(build(maxBottom + marginY / 2))
        return result
    }, [tileRects, gridWidth, cols, marginX, marginY, rowHeight])

    if (!active) {
        return null
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div ref={containerRef} className="absolute inset-0 pointer-events-none" style={{ zIndex: 6 }}>
            {boundaries.map((boundary) => (
                <InsertionStrip
                    key={Math.round(boundary.lineY)}
                    lineY={boundary.lineY}
                    gridWidth={gridWidth}
                    segments={boundary.segments}
                    zones={boundary.zones}
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
    gridWidth,
    segments,
    zones,
    getMenuItems,
}: {
    lineY: number
    gridWidth: number
    segments: LineSegment[]
    zones: InsertZone[]
    getMenuItems: (targetX: number, targetY: number) => LemonMenuItem[]
}): JSX.Element {
    const stripRef = useRef<HTMLDivElement>(null)
    const buttonRef = useRef<HTMLDivElement>(null)
    // The drop zone under the cursor, frozen with the button while the menu is open so the insert lands
    // where the user opened the menu.
    const targetRef = useRef<InsertZone | null>(null)
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
            // Only show the "+" over a drop zone — a tile bordering the line. Elsewhere, inserting would
            // land the new tile above the line (compaction floats it up), so there's no valid spot.
            const zone = zones.find((z) => x >= z.left && x <= z.right)
            buttonRef.current.style.display = zone ? '' : 'none'
            if (!zone) {
                return
            }
            targetRef.current = zone
            // Our Tailwind config sets `important: true`, so the `left-4` class is `left !important` and
            // would beat a plain inline `left`. Write with priority so the follow position actually wins.
            buttonRef.current.style.setProperty('left', `${x}px`, 'important')
        }
    }

    // Build items when the menu opens, from the frozen drop zone. Stable otherwise so the dropdown
    // overlay isn't rebuilt under the pointer on unrelated re-renders.
    const menuItems = useMemo(
        () => (targetRef.current ? getMenuItems(targetRef.current.targetX, targetRef.current.targetY) : []),
        // menuOpen forces a rebuild on open so targetRef (frozen there) picks the zone under the cursor.
        // eslint-disable-next-line react-hooks/exhaustive-deps
        [getMenuItems, menuOpen]
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

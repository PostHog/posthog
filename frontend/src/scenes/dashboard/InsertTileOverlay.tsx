import clsx from 'clsx'
import { useMemo, useRef, useState } from 'react'
import { Layout } from 'react-grid-layout'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'

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
    /** Builds the add-tile menu for an insertion at the given grid row. */
    getMenuItems: (targetY: number) => LemonMenuItem[]
}

/** A visible run of the boundary line (px), between the tiles a row cuts across. */
interface LineSegment {
    left: number
    width: number
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

    // For each boundary, the visible runs of the line: the full width minus any tile the row cuts
    // through. Drawing only in the gaps makes the line read as passing *behind* tiles instead of
    // slicing across them, while the hover strip + "+" still span the whole row.
    const segmentsByRow = useMemo(() => {
        const colWidth = (gridWidth - marginX * (cols - 1)) / cols
        const leftPx = (x: number): number => x * (colWidth + marginX)
        const widthPx = (w: number): number => w * colWidth + (w - 1) * marginX

        const byRow = new Map<number, LineSegment[]>()
        for (const targetY of boundaryRows) {
            // Tiles whose body crosses this row, padded into the column gutter so the line doesn't peek
            // through the margin right next to a covered tile.
            const covered = (layout || [])
                .filter((item) => item.y < targetY && item.y + item.h > targetY)
                .map(
                    (item) =>
                        [
                            Math.max(0, leftPx(item.x) - marginX / 2),
                            Math.min(gridWidth, leftPx(item.x) + widthPx(item.w) + marginX / 2),
                        ] as [number, number]
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
    }, [boundaryRows, layout, gridWidth, cols, marginX])

    if (!canEditDashboard || isMobileView || disabled) {
        return null
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="absolute inset-0 pointer-events-none" style={{ zIndex: 6 }}>
            {boundaryRows.map((targetY) => (
                <InsertionStrip
                    key={targetY}
                    targetY={targetY}
                    // Center the strip on the gap above the tiles that start at this row. The lower bound
                    // keeps the targetY=0 strip inside the top gap rather than clipped above the container.
                    topPx={Math.max(marginY / 2, targetY * (rowHeight + marginY) - marginY / 2)}
                    gridWidth={gridWidth}
                    segments={segmentsByRow.get(targetY) ?? [{ left: 0, width: gridWidth }]}
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
    getMenuItems,
}: {
    targetY: number
    topPx: number
    gridWidth: number
    segments: LineSegment[]
    getMenuItems: (targetY: number) => LemonMenuItem[]
}): JSX.Element {
    const stripRef = useRef<HTMLDivElement>(null)
    const buttonRef = useRef<HTMLDivElement>(null)
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
            // Our Tailwind config sets `important: true`, so the `left-4` class is `left !important` and
            // would beat a plain inline `left`. Write with priority so the follow position actually wins.
            buttonRef.current.style.setProperty('left', `${x}px`, 'important')
        }
    }

    // Stable items so the dropdown overlay isn't rebuilt under the pointer on unrelated re-renders.
    const menuItems = useMemo(() => getMenuItems(targetY), [getMenuItems, targetY])

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

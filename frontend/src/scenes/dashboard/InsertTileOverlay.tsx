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
    rowHeight: number
    /** Vertical grid margin (px) — the gap between rows where the "+" affordance sits. */
    marginY: number
    canEditDashboard: boolean
    isMobileView: boolean
    /** Hide while a drag/resize gesture is in progress. */
    disabled?: boolean
    /** Builds the add-tile menu for an insertion at the given grid row. */
    getMenuItems: (targetY: number) => LemonMenuItem[]
}

/**
 * Overlays thin hover strips in the gaps between dashboard grid rows. Hovering a strip reveals a
 * "+" that opens the same add-tile menu as the header — but the new tile is inserted at that row
 * rather than appended at the bottom. Shown to anyone with edit access, in both view and edit mode.
 */
export function InsertTileOverlay({
    layout,
    gridWidth,
    rowHeight,
    marginY,
    canEditDashboard,
    isMobileView,
    disabled,
    getMenuItems,
}: InsertTileOverlayProps): JSX.Element | null {
    // Distinct row boundaries: the top (0), the start of every tile, and the bottom of the grid.
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
    getMenuItems,
}: {
    targetY: number
    topPx: number
    gridWidth: number
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
            <div
                className={clsx(
                    'absolute left-0 right-0 top-1/2 -translate-y-1/2 h-0.5 bg-accent transition-opacity',
                    revealClass
                )}
            />
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

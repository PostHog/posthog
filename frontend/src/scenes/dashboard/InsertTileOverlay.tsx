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
    // Freeze the "+" while the pointer is pressed: repositioning it mid-click moves the DOM node out
    // from under the cursor, so the browser never completes the click and it takes a second one.
    const pointerDownRef = useRef(false)
    const [menuOpen, setMenuOpen] = useState(false)
    // Where the "+" sits along the strip — follows the cursor, frozen while the menu is open so it
    // stays anchored under the popover. Null until first hover, where it falls back to the left edge.
    const [buttonX, setButtonX] = useState<number | null>(null)

    const revealClass = menuOpen ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'

    // Map a viewport cursor X to a clamped position along the strip, keeping the "+" fully on screen.
    const clampButtonX = (clientX: number): number => {
        const rect = stripRef.current?.getBoundingClientRect()
        if (!rect) {
            return buttonX ?? BUTTON_EDGE_PADDING
        }
        const x = clientX - rect.left
        return Math.min(Math.max(x, BUTTON_EDGE_PADDING), gridWidth - BUTTON_EDGE_PADDING)
    }

    return (
        <div
            ref={stripRef}
            className="group absolute pointer-events-auto"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ left: 0, width: gridWidth, top: topPx - HOVER_HIT_HEIGHT / 2, height: HOVER_HIT_HEIGHT }}
            // Seed on enter so the "+" appears under the cursor instead of sliding in from the left.
            onMouseEnter={(e) => !menuOpen && !pointerDownRef.current && setButtonX(clampButtonX(e.clientX))}
            onMouseMove={(e) => !menuOpen && !pointerDownRef.current && setButtonX(clampButtonX(e.clientX))}
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
                className={clsx('absolute top-1/2 -translate-x-1/2 -translate-y-1/2 transition-opacity', revealClass)}
                // eslint-disable-next-line react/forbid-dom-props
                style={{ left: buttonX ?? BUTTON_EDGE_PADDING }}
            >
                <LemonMenu items={getMenuItems(targetY)} onVisibilityChange={setMenuOpen}>
                    <LemonButton
                        size="xsmall"
                        type="primary"
                        icon={<IconPlusSmall />}
                        data-attr="dashboard-inline-add-tile"
                        tooltip="Add a tile here"
                    />
                </LemonMenu>
            </div>
        </div>
    )
}

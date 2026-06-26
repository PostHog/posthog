import { useEffect, useMemo, useRef, useState } from 'react'
import { Layout } from 'react-grid-layout'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { DEFAULT_INSERTED_TILE_SIZE } from 'scenes/dashboard/tileLayouts'

interface InsertTileOverlayProps {
    /** The current breakpoint's tile layout (sm) — used to find the per-column gaps between tiles. */
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

/** A spot a new tile can drop into: a column span (`x`,`w`) and the grid row it lands at. */
interface InsertSlot {
    x: number
    w: number
    y: number
}

const slotKey = (slot: InsertSlot): string => `${slot.x}:${slot.w}:${slot.y}`

/**
 * Overlays a drop-band affordance for inserting a tile into a column gap. Moving the cursor over the
 * grid highlights the nearest gap in the column under the pointer and previews where the new tile
 * will land; the "+ Add" opens the same menu as the header but inserts at that slot, pushing only
 * that column's tiles down. Shown to anyone with edit access, in both view and edit mode.
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
    const [activeSlot, setActiveSlot] = useState<InsertSlot | null>(null)
    const [menuOpen, setMenuOpen] = useState(false)

    // react-grid-layout geometry: column width, then px helpers for a grid (x,y,w,h).
    const colWidth = (gridWidth - marginX * (cols - 1)) / cols
    const xPx = (x: number): number => x * (colWidth + marginX)
    const wPx = (w: number): number => w * colWidth + (w - 1) * marginX
    const yPx = (y: number): number => y * (rowHeight + marginY)

    // Every gap a tile can be inserted at: above and below each tile, in that tile's column span.
    // Deduped, so two stacked tiles in a column share the single gap between them.
    const slots = useMemo(() => {
        const byKey = new Map<string, InsertSlot>()
        for (const item of layout || []) {
            for (const slot of [
                { x: item.x, w: item.w, y: item.y },
                { x: item.x, w: item.w, y: item.y + item.h },
            ]) {
                byKey.set(slotKey(slot), slot)
            }
        }
        return Array.from(byKey.values())
    }, [layout])

    const active = !canEditDashboard || isMobileView || disabled ? false : true

    // Track the cursor on window (not a full-size pointer-catching layer) so tiles stay interactive.
    // Pick the nearest gap in the column under the cursor; freeze the selection while the menu is open.
    useEffect(() => {
        if (!active) {
            setActiveSlot(null)
            return
        }
        const onMove = (e: MouseEvent): void => {
            if (menuOpen) {
                return
            }
            const rect = containerRef.current?.getBoundingClientRect()
            if (!rect) {
                return
            }
            const cx = e.clientX - rect.left
            const cy = e.clientY - rect.top
            if (cx < 0 || cy < 0 || cx > rect.width || cy > rect.height) {
                setActiveSlot(null)
                return
            }
            let best: InsertSlot | null = null
            let bestDist = Infinity
            for (const slot of slots) {
                const left = xPx(slot.x)
                if (cx < left || cx > left + wPx(slot.w)) {
                    continue
                }
                const dist = Math.abs(yPx(slot.y) - marginY / 2 - cy)
                if (dist < bestDist) {
                    bestDist = dist
                    best = slot
                }
            }
            setActiveSlot((prev) => (best && prev && slotKey(best) === slotKey(prev) ? prev : best))
        }
        window.addEventListener('mousemove', onMove)
        return () => window.removeEventListener('mousemove', onMove)
        // xPx/wPx/yPx are pure fns of the px props in the dep list; slots covers `layout`.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, menuOpen, slots, gridWidth, cols, rowHeight, marginX, marginY])

    const menuItems = useMemo(
        () => (activeSlot ? getMenuItems(activeSlot.x, activeSlot.y) : []),
        [getMenuItems, activeSlot]
    )

    if (!active) {
        return null
    }

    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div ref={containerRef} className="absolute inset-0 pointer-events-none" style={{ zIndex: 6 }}>
            {activeSlot && (
                <div
                    className="absolute rounded border border-dashed border-accent bg-accent-highlight-secondary flex items-start justify-center pt-2 pointer-events-none"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        left: xPx(activeSlot.x),
                        width: wPx(activeSlot.w),
                        top: yPx(activeSlot.y),
                        height: yPx(DEFAULT_INSERTED_TILE_SIZE.h) - marginY,
                    }}
                >
                    <div className="pointer-events-auto">
                        <LemonMenu items={menuItems} onVisibilityChange={setMenuOpen}>
                            <LemonButton
                                size="small"
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
            )}
        </div>
    )
}

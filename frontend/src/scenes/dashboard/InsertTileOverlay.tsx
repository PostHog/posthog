import clsx from 'clsx'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Layout } from 'react-grid-layout'

import { IconPlusSmall } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonMenu, LemonMenuItem } from 'lib/lemon-ui/LemonMenu'
import { computeBoundaries, InsertZone, LineSegment, TileRect } from 'scenes/dashboard/insertTileGeometry'

interface InsertTileOverlayProps {
    // `layout` is unused at render but its identity change drives re-measuring (effect dep).
    layout: Layout | undefined
    gridWidth: number
    cols: number
    rowHeight: number
    marginX: number
    marginY: number
    canEditDashboard: boolean
    isMobileView: boolean
    disabled?: boolean
    getMenuItems: (targetX: number, targetY: number, targetW?: number) => LemonMenuItem[]
}

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

    const boundaries = useMemo(
        () => computeBoundaries(tileRects, { gridWidth, cols, marginX, marginY, rowHeight }),
        [tileRects, gridWidth, cols, marginX, marginY, rowHeight]
    )

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
                    gridRow={boundary.gridRow}
                    gridWidth={gridWidth}
                    cols={cols}
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

interface InsertTarget {
    targetX: number
    targetY: number
    targetW?: number
}

function InsertionStrip({
    lineY,
    gridRow,
    gridWidth,
    cols,
    segments,
    zones,
    getMenuItems,
}: {
    lineY: number
    gridRow: number
    gridWidth: number
    cols: number
    segments: LineSegment[]
    zones: InsertZone[]
    getMenuItems: (targetX: number, targetY: number, targetW?: number) => LemonMenuItem[]
}): JSX.Element {
    const stripRef = useRef<HTMLDivElement>(null)
    const buttonRef = useRef<HTMLDivElement>(null)
    // Where the insert will land, frozen with the button while the menu is open so it matches the spot
    // the user opened the menu over.
    const targetRef = useRef<InsertTarget | null>(null)
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
            // Only show the "+" in a real gap (not on top of a tile). Over a tile bordering the line we
            // insert into that column; over empty gap space we insert full-width so it still lands at the
            // line (compaction would otherwise float a column-width tile up above it).
            const inGap = segments.some((segment) => x >= segment.left && x <= segment.left + segment.width)
            buttonRef.current.style.display = inGap ? '' : 'none'
            if (!inGap) {
                return
            }
            const zone = zones.find((z) => x >= z.left && x <= z.right)
            targetRef.current = zone
                ? { targetX: zone.targetX, targetY: zone.targetY }
                : { targetX: 0, targetY: gridRow, targetW: cols }
            // Our Tailwind config sets `important: true`, so the `left-4` class is `left !important` and
            // would beat a plain inline `left`. Write with priority so the follow position actually wins.
            buttonRef.current.style.setProperty('left', `${x}px`, 'important')
        }
    }

    // Build items when the menu opens, from the frozen target. Stable otherwise so the dropdown overlay
    // isn't rebuilt under the pointer on unrelated re-renders.
    const menuItems = useMemo(
        () => {
            const target = targetRef.current
            return target ? getMenuItems(target.targetX, target.targetY, target.targetW) : []
        },
        // menuOpen forces a rebuild on open so targetRef (frozen there) picks the spot under the cursor.
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

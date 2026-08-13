import React, { useEffect, useRef, useState } from 'react'

import { DashboardResizeHandles } from 'lib/components/Cards/handles'

export type EditModeEdge = 'n' | 's' | 'w' | 'e' | 'nw' | 'ne' | 'sw' | 'se'

interface EditModeEdgeOverlayProps {
    onEnterEditMode: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
}

const EDGE_ZONE_DATA_ATTR = 'dashboard-edit-mode-from-card-edge'

const edgeOverlayBaseStyle: React.CSSProperties = {
    position: 'absolute',
    zIndex: 5,
    padding: 0,
    margin: 0,
    border: 'none',
    background: 'none',
}

// Top/bottom zones hug the border and reach mostly *into* the tile: the inline "insert tile" overlay owns the
// row gap between tiles (see InsertTileOverlay), so keeping these off the gap avoids fighting it for the same
// pixels. They still win the shared border pixel via a higher z-index. Left/right never touch the insert line.
const TOP_BOTTOM_Z = 7
// Corners sit above edges so a press in the corner resolves to the diagonal handle.
const cornerZoneStyle: React.CSSProperties = { zIndex: TOP_BOTTOM_Z, width: 18, height: 18 }

const zones: { edge: EditModeEdge; style: React.CSSProperties; cursor: React.CSSProperties['cursor'] }[] = [
    // Shallow on top (the card header/menu lives just below) and deeper on the bottom for a comfortable target.
    { edge: 'n', style: { left: 0, right: 0, top: -2, height: 10, zIndex: TOP_BOTTOM_Z }, cursor: 'ns-resize' },
    { edge: 's', style: { left: 0, right: 0, bottom: -2, height: 14, zIndex: TOP_BOTTOM_Z }, cursor: 'ns-resize' },
    { edge: 'w', style: { top: 0, bottom: 0, left: -6, width: 12 }, cursor: 'ew-resize' },
    { edge: 'e', style: { top: 0, bottom: 0, right: -6, width: 12 }, cursor: 'ew-resize' },
    { edge: 'nw', style: { ...cornerZoneStyle, top: -2, left: -2 }, cursor: 'nw-resize' },
    { edge: 'ne', style: { ...cornerZoneStyle, top: -2, right: -2 }, cursor: 'ne-resize' },
    { edge: 'sw', style: { ...cornerZoneStyle, bottom: -2, left: -2 }, cursor: 'sw-resize' },
    { edge: 'se', style: { ...cornerZoneStyle, bottom: -2, right: -2 }, cursor: 'se-resize' },
]

/**
 * Overlay scrollbars (macOS default, and Chromium headless) occupy no layout space, so their exact
 * bounds cannot be measured. They render inside the scroll container along its bottom/right edge;
 * 16px matches the macOS hover-expanded track and comfortably covers Chromium's overlay thumb.
 */
const OVERLAY_SCROLLBAR_BAND = 16

const isScrollableOverflow = (overflow: string): boolean =>
    // 'overlay' is legacy WebKit; Chrome computes it to 'auto' but include it for safety.
    overflow === 'auto' || overflow === 'scroll' || overflow === 'overlay'

/**
 * Whether the viewport point (x, y) lies on a functional scrollbar of `el`.
 * "Functional" means the content actually overflows on that axis, so a press there would grab the
 * scrollbar rather than hit an empty reserved gutter. Classic scrollbars occupy layout space
 * (`offsetHeight - clientHeight`), which gives their exact bounds. Overlay scrollbars (macOS
 * default) occupy none, so for a scrollable element without a gutter the edge band where the
 * overlay scrollbar materializes counts as scrollbar territory even while the thumb is hidden;
 * a press there while it's hidden just falls through to the content, matching native behavior.
 */
export function isPointInScrollbarGutter(el: HTMLElement, x: number, y: number): boolean {
    const style = window.getComputedStyle(el)
    const borderTop = parseFloat(style.borderTopWidth) || 0
    const borderBottom = parseFloat(style.borderBottomWidth) || 0
    const borderLeft = parseFloat(style.borderLeftWidth) || 0
    const borderRight = parseFloat(style.borderRightWidth) || 0
    const rect = el.getBoundingClientRect()

    // offsetHeight spans the border box; clientHeight excludes borders and the horizontal scrollbar,
    // so the difference minus borders is the scrollbar's rendered height (0 for overlay scrollbars).
    // The > 1 threshold absorbs the integer rounding of offset/client dimensions.
    const horizontalGutter = el.offsetHeight - el.clientHeight - borderTop - borderBottom
    const canScrollX = el.scrollWidth - el.clientWidth > 1
    const horizontalBand =
        horizontalGutter > 1 && canScrollX
            ? horizontalGutter
            : canScrollX && isScrollableOverflow(style.overflowX)
              ? OVERLAY_SCROLLBAR_BAND
              : 0
    if (horizontalBand > 0) {
        const bandTop = rect.bottom - borderBottom - horizontalBand
        if (
            y >= bandTop &&
            y <= rect.bottom - borderBottom &&
            x >= rect.left + borderLeft &&
            x <= rect.right - borderRight
        ) {
            return true
        }
    }

    const verticalGutter = el.offsetWidth - el.clientWidth - borderLeft - borderRight
    const canScrollY = el.scrollHeight - el.clientHeight > 1
    const verticalBand =
        verticalGutter > 1 && canScrollY
            ? verticalGutter
            : canScrollY && isScrollableOverflow(style.overflowY)
              ? OVERLAY_SCROLLBAR_BAND
              : 0
    if (verticalBand > 0) {
        const bandLeft = style.direction === 'rtl' ? rect.left + borderLeft : rect.right - borderRight - verticalBand
        if (
            x >= bandLeft &&
            x <= bandLeft + verticalBand &&
            y >= rect.top + borderTop &&
            y <= rect.bottom - borderBottom
        ) {
            return true
        }
    }

    return false
}

/** Whether any element of the card under the viewport point shows a functional scrollbar there. */
function pointIsOverScrollbarInside(container: HTMLElement, x: number, y: number): boolean {
    return document
        .elementsFromPoint(x, y)
        .some(
            (el) =>
                el instanceof HTMLElement &&
                el.dataset.attr !== EDGE_ZONE_DATA_ATTR &&
                container.contains(el) &&
                isPointInScrollbarGutter(el, x, y)
        )
}

/**
 * In edit mode react-grid-layout's resize handles cover the card edges — the south handle is 32px
 * tall and reaches 24px into the tile (see DashboardItems.scss), fully burying a table's horizontal
 * scrollbar — so they must yield to scrollbars the same way the view-mode zones above do. One
 * document-level watcher covers every tile: it hands a hovered handle's pixels to the scrollbar via
 * `pointer-events: none` and re-arms it once the pointer leaves. The capture-phase mousedown guard
 * covers what the hover hand-off can't: a press that lands before any mousemove, or a press on the
 * scrollbar itself, which would otherwise bubble into react-grid-layout and start a resize or tile
 * drag. Stopping propagation (without preventDefault) keeps the native scrollbar interaction alive.
 */
export function useResizeHandleScrollbarPassThrough(enabled: boolean): void {
    useEffect(() => {
        if (!enabled) {
            return
        }
        const yielded = new Set<HTMLElement>()

        const rearm = (event: MouseEvent): void => {
            for (const handle of yielded) {
                const gridItem = handle.closest('.react-grid-item')
                const rect = handle.getBoundingClientRect()
                const inHandle =
                    handle.isConnected &&
                    event.clientX >= rect.left &&
                    event.clientX <= rect.right &&
                    event.clientY >= rect.top &&
                    event.clientY <= rect.bottom
                if (
                    !inHandle ||
                    !(gridItem instanceof HTMLElement) ||
                    !pointIsOverScrollbarInside(gridItem, event.clientX, event.clientY)
                ) {
                    handle.style.pointerEvents = ''
                    yielded.delete(handle)
                }
            }
        }

        const handleMove = (event: MouseEvent): void => {
            if (event.buttons !== 0) {
                return // don't re-target pixels mid-drag or mid-resize
            }
            rearm(event)
            const hovered = event.target instanceof Element ? event.target.closest('.react-resizable-handle') : null
            const gridItem = hovered?.closest('.react-grid-item')
            if (
                !(hovered instanceof HTMLElement) ||
                !(gridItem instanceof HTMLElement) ||
                yielded.has(hovered) ||
                !pointIsOverScrollbarInside(gridItem, event.clientX, event.clientY)
            ) {
                return
            }
            // Corner handles overlap the edge handles at the ends, so yield every handle stacked on
            // the point at once — otherwise the one beneath swallows a press until its own mousemove.
            for (const handle of gridItem.querySelectorAll<HTMLElement>('.react-resizable-handle')) {
                const rect = handle.getBoundingClientRect()
                if (
                    event.clientX >= rect.left &&
                    event.clientX <= rect.right &&
                    event.clientY >= rect.top &&
                    event.clientY <= rect.bottom
                ) {
                    handle.style.pointerEvents = 'none'
                    yielded.add(handle)
                }
            }
        }

        const handlePressCapture = (event: MouseEvent): void => {
            const gridItem = event.target instanceof Element ? event.target.closest('.react-grid-item') : null
            if (gridItem instanceof HTMLElement && pointIsOverScrollbarInside(gridItem, event.clientX, event.clientY)) {
                event.stopPropagation()
            }
        }

        document.addEventListener('mousemove', handleMove)
        document.addEventListener('mousedown', handlePressCapture, true)
        return () => {
            document.removeEventListener('mousemove', handleMove)
            document.removeEventListener('mousedown', handlePressCapture, true)
            for (const handle of yielded) {
                handle.style.pointerEvents = ''
            }
        }
    }, [enabled])
}

export const EditModeEdgeOverlay: React.FC<EditModeEdgeOverlayProps> = ({ onEnterEditMode }) => {
    const [hovering, setHovering] = useState(false)
    // Count entered zones rather than toggling a boolean, so following the border across overlapping
    // edge/corner zones never dips to "not hovering" for a frame and flickers the handles.
    const hoverCount = useRef(0)
    // Zones whose pixels currently sit on top of a scrollbar of the tile's content. They get
    // `pointer-events: none` so presses and wheel events reach the scrollbar natively: a native
    // scrollbar drag only engages when the browser hit-tests the pointer to the scrollable element
    // itself, so an intercept-then-forward approach cannot work. The main case is a table insight
    // whose horizontal scrollbar renders in the card's bottom pixels, exactly under the "s" zone.
    const [scrollbarPassThroughEdges, setScrollbarPassThroughEdges] = useState<ReadonlySet<EditModeEdge>>(new Set())
    const zoneRefs = useRef(new Map<EditModeEdge, HTMLDivElement | null>())

    const releaseHover = (): void => {
        hoverCount.current = Math.max(0, hoverCount.current - 1)
        if (hoverCount.current === 0) {
            setHovering(false)
        }
    }

    const evaluateScrollbarPassThrough = (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge): void => {
        const container = event.currentTarget.parentElement
        if (!container || scrollbarPassThroughEdges.has(edge)) {
            return
        }
        const { clientX, clientY } = event
        if (!pointIsOverScrollbarInside(container, clientX, clientY)) {
            return
        }
        // Corner zones paint above edge zones, so several zones can stack on these pixels. Yield every
        // zone whose rect contains the point, not just the hovered one: a zone beneath only receives its
        // own mousemove after the one above yields, and until then it would swallow a press aimed at the
        // scrollbar (handlePress keeps it out of edit mode, but the press reaches no scrollbar either).
        setScrollbarPassThroughEdges((prev) => {
            let next: Set<EditModeEdge> | null = null
            for (const [zoneEdge, zone] of zoneRefs.current) {
                if (!zone || prev.has(zoneEdge)) {
                    continue
                }
                const rect = zone.getBoundingClientRect()
                const containsPoint =
                    clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom
                if (zoneEdge === edge || containsPoint) {
                    next = next ?? new Set(prev)
                    next.add(zoneEdge)
                }
            }
            return next ?? prev
        })
        // The zone's own mouseleave won't fire once it ignores pointer events, so release here.
        releaseHover()
    }

    useEffect(() => {
        if (scrollbarPassThroughEdges.size === 0) {
            return
        }
        // While any zone is letting events through, watch the pointer at the document level and
        // re-enable the zone once the pointer is no longer over the scrollbar beneath it.
        const handleMove = (event: MouseEvent): void => {
            setScrollbarPassThroughEdges((prev) => {
                let next: Set<EditModeEdge> | null = null
                for (const edge of prev) {
                    const zone = zoneRefs.current.get(edge)
                    const container = zone?.parentElement
                    const rect = zone?.getBoundingClientRect()
                    const inZone =
                        !!rect &&
                        event.clientX >= rect.left &&
                        event.clientX <= rect.right &&
                        event.clientY >= rect.top &&
                        event.clientY <= rect.bottom
                    if (!inZone || !container || !pointIsOverScrollbarInside(container, event.clientX, event.clientY)) {
                        next = next ?? new Set(prev)
                        next.delete(edge)
                    }
                }
                return next ?? prev
            })
        }
        document.addEventListener('mousemove', handleMove)
        return () => document.removeEventListener('mousemove', handleMove)
    }, [scrollbarPassThroughEdges])

    const handlePress = (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge): void => {
        // A fast press can land before any mousemove had a chance to hand the zone's pixels over to
        // the scrollbar below. The press is lost either way (it targeted the zone), but it must not
        // throw the user into edit mode when they were aiming at a scrollbar.
        const container = event.currentTarget.parentElement
        if (container && pointIsOverScrollbarInside(container, event.clientX, event.clientY)) {
            return
        }
        // Treat any press (click or drag attempt) as intent to edit
        event.preventDefault()
        event.stopPropagation()
        onEnterEditMode(event, edge)
    }

    return (
        <>
            {hovering && <DashboardResizeHandles />}
            {zones.map(({ edge, style, cursor }) => (
                <div
                    key={edge}
                    ref={(el) => {
                        zoneRefs.current.set(edge, el)
                    }}
                    onMouseDown={(event) => handlePress(event, edge)}
                    onMouseMove={(event) => evaluateScrollbarPassThrough(event, edge)}
                    onMouseEnter={(event) => {
                        hoverCount.current += 1
                        setHovering(true)
                        evaluateScrollbarPassThrough(event, edge)
                    }}
                    onMouseLeave={() => releaseHover()}
                    aria-hidden="true"
                    title="Click to edit layout"
                    data-attr={EDGE_ZONE_DATA_ATTR}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        ...edgeOverlayBaseStyle,
                        ...style,
                        cursor,
                        ...(scrollbarPassThroughEdges.has(edge) ? { pointerEvents: 'none' } : {}),
                    }}
                />
            ))}
        </>
    )
}

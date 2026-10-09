import {
    autoUpdate,
    computePosition,
    flip,
    FloatingPortal,
    offset,
    shift,
    type VirtualElement,
} from '@floating-ui/react'
import React, { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { useChartLayout } from '../core/chart-context'
import type { TooltipContext } from '../core/types'

interface TooltipProps<Meta> {
    context: TooltipContext<Meta>
    renderTooltip: (ctx: TooltipContext<Meta>) => React.ReactNode
    placement?: 'follow-data' | 'top' | 'cursor'
}

const TOOLTIP_MIDDLEWARE = [offset(12), flip(), shift({ padding: 8 })]
const DEFAULT_TOOLTIP_Z_INDEX = 9999

export function Tooltip<Meta = unknown>({
    context,
    renderTooltip,
    placement = 'follow-data',
}: TooltipProps<Meta>): React.ReactElement {
    const { theme } = useChartLayout()
    const zIndex = theme.tooltipZIndex ?? DEFAULT_TOOLTIP_Z_INDEX
    const { left: canvasLeft, top: canvasTop } = context.canvasBounds
    // `cursor` follows the mouse (falling back to the data anchor on non-mousemove rebuilds);
    // `top` pins y to the canvas top; `follow-data` anchors at the hovered data point.
    const cursor = placement === 'cursor' ? context.hoverPosition : null
    let anchorX: number
    let anchorY: number
    let anchorWidth: number
    if (cursor) {
        anchorX = canvasLeft + cursor.x
        anchorY = canvasTop + cursor.y
        anchorWidth = 0
    } else if (placement === 'top') {
        anchorX = canvasLeft + context.position.x
        anchorY = canvasTop
        // Anchor at the band's right edge via the reference width + `right-start` so the tooltip
        // lands beside the bar, not over it. `flip()` handles overflow.
        anchorWidth = context.position.width ?? 0
    } else {
        anchorX = canvasLeft + context.position.x
        anchorY = canvasTop + context.position.y
        anchorWidth = 0
    }

    const [floating, setFloating] = useState<HTMLDivElement | null>(null)
    const anchorRef = useRef({ x: anchorX, y: anchorY, width: anchorWidth })
    const updateRef = useRef<(() => void) | null>(null)
    const floatingPlacement = placement === 'follow-data' ? 'right' : 'right-start'

    // Position outside React state: `useFloating` re-renders synchronously on every anchor move
    // (`setPositionReference`, then `flushSync` with the new position), and on a busy page those
    // renders count towards React's nested update limit (error #185).
    const virtualReference = useMemo<VirtualElement>(
        () => ({
            getBoundingClientRect() {
                const { x, y, width } = anchorRef.current
                const left = x - width / 2
                const right = x + width / 2
                return { x: left, y, width, height: 0, top: y, right, bottom: y, left }
            },
        }),
        []
    )

    useLayoutEffect(() => {
        anchorRef.current = { x: anchorX, y: anchorY, width: anchorWidth }
        updateRef.current?.()
    }, [anchorX, anchorY, anchorWidth])

    useLayoutEffect(() => {
        if (!floating) {
            return
        }
        const update = (): void => {
            void computePosition(virtualReference, floating, {
                placement: floatingPlacement,
                strategy: 'fixed',
                middleware: TOOLTIP_MIDDLEWARE,
            }).then(({ x, y }) => {
                const dpr = window.devicePixelRatio || 1
                floating.style.transform = `translate(${Math.round(x * dpr) / dpr}px, ${Math.round(y * dpr) / dpr}px)`
            })
        }
        updateRef.current = update
        // Re-run the middleware (notably `flip`/`shift`) once the portaled tooltip reaches its
        // real `max-content` size and whenever the page scrolls/resizes — without this the first
        // position is computed against a still-zero-width element, so `flip` never kicks in and
        // the tooltip can stay clipped off the right edge (e.g. on the last bar of a chart).
        const cleanup = autoUpdate(virtualReference, floating, update)
        return () => {
            updateRef.current = null
            cleanup()
        }
    }, [floating, virtualReference, floatingPlacement])

    return (
        <FloatingPortal>
            <div
                ref={setFloating}
                // Marker so useChartInteraction can identify events originating inside the
                // tooltip — it lives outside the chart wrapper via FloatingPortal, so DOM
                // ancestry can't be used to detect it.
                data-hog-charts-tooltip=""
                className={context.isPinned ? 'hog-charts-tooltip--pinned' : undefined}
                style={{
                    position: 'fixed',
                    left: 0,
                    top: 0,
                    pointerEvents: context.isPinned ? 'auto' : 'none',
                    width: 'max-content',
                    zIndex,
                }}
            >
                {renderTooltip(context)}
            </div>
        </FloatingPortal>
    )
}

import { flip, FloatingPortal, offset, shift, useFloating, type VirtualElement } from '@floating-ui/react'
import React, { useLayoutEffect, useMemo } from 'react'

import type { TooltipContext } from '../core/types'

interface TooltipProps<Meta> {
    context: TooltipContext<Meta>
    renderTooltip: (ctx: TooltipContext<Meta>) => React.ReactNode
    placement?: 'follow-data' | 'top'
}

const TOOLTIP_MIDDLEWARE = [offset(12), flip(), shift({ padding: 8 })]

export function Tooltip<Meta = unknown>({
    context,
    renderTooltip,
    placement = 'follow-data',
}: TooltipProps<Meta>): React.ReactElement {
    // In `top` placement the y position is anchored to the canvas top and `position.y` is
    // unused, so we depend on the resolved y rather than `position.y` directly — otherwise
    // mousemove rebuilds the virtual reference and triggers a Floating-UI reposition pass
    // for nothing.
    const y = placement === 'top' ? context.canvasBounds.top : context.canvasBounds.top + context.position.y
    const virtualReference = useMemo<VirtualElement>(
        () => ({
            getBoundingClientRect() {
                const x = context.canvasBounds.left + context.position.x
                return {
                    x,
                    y,
                    width: 0,
                    height: 0,
                    top: y,
                    right: x,
                    bottom: y,
                    left: x,
                }
            },
        }),
        [context.position.x, y, context.canvasBounds]
    )

    const { refs, floatingStyles } = useFloating({
        placement: placement === 'top' ? 'right-start' : 'right',
        strategy: 'fixed',
        middleware: TOOLTIP_MIDDLEWARE,
    })

    useLayoutEffect(() => {
        refs.setPositionReference(virtualReference)
    }, [virtualReference, refs])

    return (
        <FloatingPortal>
            <div
                ref={refs.setFloating}
                // Marker so useChartInteraction can identify events originating inside the
                // tooltip — it lives outside the chart wrapper via FloatingPortal, so DOM
                // ancestry can't be used to detect it.
                data-hog-charts-tooltip=""
                className={context.isPinned ? 'hog-charts-tooltip--pinned' : undefined}
                style={{
                    ...floatingStyles,
                    pointerEvents: context.isPinned ? 'auto' : 'none',
                    width: 'max-content',
                    zIndex: 'var(--z-chart-tooltip)',
                }}
            >
                {renderTooltip(context)}
            </div>
        </FloatingPortal>
    )
}

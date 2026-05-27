import { flip, FloatingPortal, offset, shift, useFloating, type VirtualElement } from '@floating-ui/react'
import React, { useLayoutEffect, useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'
import type { TooltipContext } from '../core/types'

interface TooltipProps<Meta> {
    context: TooltipContext<Meta>
    renderTooltip: (ctx: TooltipContext<Meta>) => React.ReactNode
    placement?: 'follow-data' | 'top'
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
    // `top` placement pins y to the canvas top, ignoring position.y (no per-mousemove reposition).
    const y = placement === 'top' ? context.canvasBounds.top : context.canvasBounds.top + context.position.y
    // Anchor at band's right edge via `right-start` so the tooltip lands beside the bar,
    // not over it. Only used for `top` placement; `flip()` handles overflow.
    const referenceWidth = placement === 'top' ? (context.position.width ?? 0) : 0
    const virtualReference = useMemo<VirtualElement>(
        () => ({
            getBoundingClientRect() {
                const centerX = context.canvasBounds.left + context.position.x
                const left = centerX - referenceWidth / 2
                const right = centerX + referenceWidth / 2
                return {
                    x: left,
                    y,
                    width: referenceWidth,
                    height: 0,
                    top: y,
                    right,
                    bottom: y,
                    left,
                }
            },
        }),
        [context.position.x, y, referenceWidth, context.canvasBounds]
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
                    zIndex,
                }}
            >
                {renderTooltip(context)}
            </div>
        </FloatingPortal>
    )
}

import { flip, FloatingPortal, offset, shift, useFloating, type VirtualElement } from '@floating-ui/react'
import React, { useLayoutEffect, useMemo } from 'react'

import type { TooltipContext } from '../core/types'

interface TooltipProps<Meta> {
    context: TooltipContext<Meta>
    renderTooltip: (ctx: TooltipContext<Meta>) => React.ReactNode
    placement?: 'follow-data' | 'top'
}

export function Tooltip<Meta = unknown>({
    context,
    renderTooltip,
    placement = 'follow-data',
}: TooltipProps<Meta>): React.ReactElement {
    const virtualReference = useMemo<VirtualElement>(
        () => ({
            getBoundingClientRect() {
                const x = context.canvasBounds.left + context.position.x
                const y = placement === 'top' ? context.canvasBounds.top : context.canvasBounds.top + context.position.y
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
        [context.position.x, placement === 'follow-data' ? context.position.y : null, context.canvasBounds, placement]
    )

    const { refs, floatingStyles } = useFloating({
        placement: placement === 'top' ? 'right-start' : 'right',
        strategy: 'fixed',
        middleware: [offset(12), flip(), shift({ padding: 8 })],
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
                    zIndex: 'var(--z-tooltip)',
                }}
            >
                {renderTooltip(context)}
            </div>
        </FloatingPortal>
    )
}

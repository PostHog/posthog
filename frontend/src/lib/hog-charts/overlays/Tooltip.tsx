import { flip, offset, shift, useFloating, type VirtualElement } from '@floating-ui/react'
import React, { useLayoutEffect, useMemo } from 'react'

import type { TooltipContext } from '../core/types'

interface TooltipProps<Meta> {
    context: TooltipContext<Meta>
    renderTooltip: (ctx: TooltipContext<Meta>) => React.ReactNode
}

export function Tooltip<Meta = unknown>({ context, renderTooltip }: TooltipProps<Meta>): React.ReactElement {
    const virtualReference = useMemo<VirtualElement>(
        () => ({
            getBoundingClientRect() {
                const x = context.canvasBounds.left + context.position.x
                const y = context.canvasBounds.top + context.position.y
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
        [context.position.x, context.position.y, context.canvasBounds]
    )

    const { refs, floatingStyles } = useFloating({
        placement: 'right',
        strategy: 'fixed',
        middleware: [offset(12), flip(), shift({ padding: 8 })],
    })

    // useLayoutEffect runs synchronously before paint, so floating-ui has the
    // virtual reference ready by the first frame — no positioning flash.
    useLayoutEffect(() => {
        refs.setPositionReference(virtualReference)
    }, [virtualReference, refs])

    return (
        <div
            ref={refs.setFloating}
            // Marker so the interaction hook can distinguish scroll events that originate
            // inside the tooltip (e.g. scrollable long content) from chart/page scrolls,
            // which should dismiss a pinned tooltip.
            data-hog-charts-tooltip=""
            className={context.isPinned ? 'InsightTooltipWrapper--pinned' : undefined}
            style={{
                ...floatingStyles,
                pointerEvents: context.isPinned ? 'auto' : 'none',
                width: 'max-content',
                zIndex: 10,
            }}
        >
            {renderTooltip(context)}
        </div>
    )
}

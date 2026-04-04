import { flip, offset, shift, useFloating } from '@floating-ui/react'
import React, { useEffect, useMemo } from 'react'

import type { TooltipContext } from '../core/types'

interface TooltipProps {
    context: TooltipContext
    renderTooltip: (ctx: TooltipContext) => React.ReactNode
}

export function Tooltip({ context, renderTooltip }: TooltipProps): React.ReactElement {
    const virtualReference = useMemo(
        () => ({
            getBoundingClientRect() {
                return {
                    x: context.canvasBounds.left + context.position.x,
                    y: context.canvasBounds.top + context.position.y,
                    width: 0,
                    height: 0,
                    top: context.canvasBounds.top + context.position.y,
                    right: context.canvasBounds.left + context.position.x,
                    bottom: context.canvasBounds.top + context.position.y,
                    left: context.canvasBounds.left + context.position.x,
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

    useEffect(() => {
        refs.setPositionReference(virtualReference)
    }, [virtualReference, refs])

    return (
        <div
            ref={refs.setFloating}
            style={{
                ...floatingStyles,
                pointerEvents: 'none',
                width: 'max-content',
                zIndex: 10,
            }}
        >
            {renderTooltip(context)}
        </div>
    )
}

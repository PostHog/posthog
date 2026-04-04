import { flip, offset, shift, useFloating, type VirtualElement } from '@floating-ui/react'
import React, { useMemo } from 'react'

import type { TooltipContext } from '../core/types'

interface TooltipProps {
    context: TooltipContext
    renderTooltip: (ctx: TooltipContext) => React.ReactNode
}

export function Tooltip({ context, renderTooltip }: TooltipProps): React.ReactElement {
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
        elements: { reference: virtualReference },
    })

    return (
        <div
            ref={refs.setFloating}
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

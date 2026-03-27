import React, { useRef } from 'react'

import type { TooltipContext } from '../core/types'

interface TooltipProps {
    context: TooltipContext
    renderTooltip: (context: TooltipContext) => React.ReactNode
}

export function Tooltip({ context, renderTooltip }: TooltipProps): React.ReactElement {
    const tooltipRef = useRef<HTMLDivElement>(null)

    // Position tooltip: prefer right of crosshair, flip left if near edge
    const tooltipWidth = tooltipRef.current?.offsetWidth ?? 200
    const spaceRight = context.canvasBounds.width - context.position.x
    const showOnLeft = spaceRight < tooltipWidth + 24

    const left = showOnLeft ? context.position.x - tooltipWidth - 16 : context.position.x + 16
    const top = Math.max(
        context.canvasBounds.top > 0 ? 0 : 8,
        Math.min(context.position.y - 16, context.canvasBounds.height - 100)
    )

    return (
        <div
            ref={tooltipRef}
            style={{
                position: 'absolute',
                left: Math.max(0, left),
                top,
                pointerEvents: 'none',
                zIndex: 10,
            }}
        >
            {renderTooltip(context)}
        </div>
    )
}

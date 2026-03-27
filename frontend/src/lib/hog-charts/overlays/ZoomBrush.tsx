import React from 'react'

import type { ChartDimensions } from '../core/types'

interface ZoomBrushProps {
    startX: number
    currentX: number
    dimensions: ChartDimensions
}

export function ZoomBrush({ startX, currentX, dimensions }: ZoomBrushProps): React.ReactElement {
    const left = Math.max(dimensions.plotLeft, Math.min(startX, currentX))
    const right = Math.min(dimensions.plotLeft + dimensions.plotWidth, Math.max(startX, currentX))
    const width = right - left

    return (
        <div
            style={{
                position: 'absolute',
                left,
                top: dimensions.plotTop,
                width,
                height: dimensions.plotHeight,
                backgroundColor: 'rgba(29, 74, 255, 0.1)',
                border: '1px solid rgba(29, 74, 255, 0.3)',
                pointerEvents: 'none',
            }}
        />
    )
}

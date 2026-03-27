import React from 'react'

import type { ChartDimensions } from '../core/types'

interface CrosshairProps {
    x: number
    dimensions: ChartDimensions
    color?: string
}

export function Crosshair({ x, dimensions, color = 'rgba(0, 0, 0, 0.2)' }: CrosshairProps): React.ReactElement {
    return (
        <div
            style={{
                position: 'absolute',
                left: x,
                top: dimensions.plotTop,
                width: 1,
                height: dimensions.plotHeight,
                backgroundColor: color,
                pointerEvents: 'none',
            }}
        />
    )
}

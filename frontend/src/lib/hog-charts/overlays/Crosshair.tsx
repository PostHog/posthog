import React from 'react'

import { useChartHover, useChartLayout } from '../core/chart-context'

interface CrosshairProps {
    color?: string
}

export function Crosshair({ color = 'rgba(0, 0, 0, 0.2)' }: CrosshairProps): React.ReactElement | null {
    const { scales, dimensions, labels } = useChartLayout()
    const { hoverIndex } = useChartHover()

    if (hoverIndex < 0) {
        return null
    }

    const x = scales.x(labels[hoverIndex])
    if (x == null) {
        return null
    }

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

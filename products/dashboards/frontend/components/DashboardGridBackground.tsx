import { useId } from 'react'
import { calcGridCellDimensions } from 'react-grid-layout/core'

interface DashboardGridBackgroundProps {
    width: number
    cols: number
    rowHeight: number
    margin: [number, number]
    height?: number
}

export function DashboardGridBackground({
    width,
    cols,
    rowHeight,
    margin,
    height,
}: DashboardGridBackgroundProps): JSX.Element {
    const patternId = useId()
    const { cellWidth, cellHeight, gapX, gapY } = calcGridCellDimensions({
        width,
        cols,
        rowHeight,
        margin,
        containerPadding: [0, 0],
    })
    const rowCount = height ? Math.ceil((height + gapY) / (cellHeight + gapY)) : 10
    const totalHeight = rowCount * (cellHeight + gapY) - gapY

    return (
        <svg
            className="absolute top-0 left-0 pointer-events-none"
            width={width}
            height={totalHeight}
            aria-hidden="true"
        >
            <defs>
                <pattern
                    id={patternId}
                    width={cellWidth + gapX}
                    height={cellHeight + gapY}
                    patternUnits="userSpaceOnUse"
                >
                    <rect
                        width={Math.max(0, cellWidth)}
                        height={cellHeight}
                        rx={4}
                        fill="var(--color-bg-surface-secondary)"
                    />
                </pattern>
            </defs>
            <rect width={width} height={totalHeight} fill={`url(#${patternId})`} />
        </svg>
    )
}

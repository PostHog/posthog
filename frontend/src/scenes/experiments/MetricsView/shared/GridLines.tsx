import { COLORS } from './colors'

interface GridLinesProps {
    tickValues: number[]
    scale: (value: number) => number
    height: number
    zeroLineColor?: string
    gridLineColor?: string
    zeroLineWidth?: number
    gridLineWidth?: number
    opacity?: number
}

/**
 * Renders vertical grid lines for experiment charts.
 * Zero line is rendered with different styling to emphasize the baseline.
 */
export function GridLines({
    tickValues,
    scale,
    height,
    zeroLineColor = COLORS.ZERO_LINE,
    gridLineColor = COLORS.BOUNDARY_LINES,
    zeroLineWidth = 1,
    gridLineWidth = 0.5,
    opacity = 0.3,
}: GridLinesProps): JSX.Element {
    return (
        <>
            {tickValues.map((value) => {
                const x = scale(value)
                const isZeroLine = value === 0
                return (
                    <line
                        key={value}
                        x1={x}
                        y1={0}
                        x2={x}
                        y2={height}
                        stroke={isZeroLine ? zeroLineColor : gridLineColor}
                        strokeWidth={isZeroLine ? zeroLineWidth : gridLineWidth}
                        opacity={opacity}
                    />
                )
            })}
        </>
    )
}

import { COLORS } from '../shared/colors'
import { formatTickValue } from '../shared/utils'

interface TickLabelsProps {
    tickValues: number[]
    scale: (value: number) => number
    y: number
    viewBoxWidth?: number
    fontSize?: number
    fontWeight?: string | number
    textColor?: string
    textAnchor?: 'start' | 'middle' | 'end'
    dominantBaseline?: 'auto' | 'middle' | 'hanging'
    edgeThreshold?: number
}

/**
 * Renders tick labels for experiment charts.
 * Uses formatTickValue to display percentages with appropriate precision.
 */
export function TickLabels({
    tickValues,
    scale,
    y,
    viewBoxWidth = 800,
    fontSize = 9,
    fontWeight = '600',
    textColor = COLORS.TICK_TEXT_COLOR,
    textAnchor = 'middle',
    dominantBaseline = 'middle',
    edgeThreshold = 0.06,
}: TickLabelsProps): JSX.Element {
    return (
        <>
            {tickValues.map((value) => {
                const x = scale(value)
                const position = x / viewBoxWidth

                // Hide labels that are too close to the edges to prevent clipping
                if (position < edgeThreshold || position > 1 - edgeThreshold) {
                    return null
                }

                return (
                    <text
                        key={`text-${value}`}
                        x={x}
                        y={y}
                        textAnchor={textAnchor}
                        dominantBaseline={dominantBaseline}
                        fill={textColor}
                        fontWeight={fontWeight}
                        className="tick-label-fixed-size"
                        style={{
                            fontSize: `${fontSize}px`,
                        }}
                    >
                        {formatTickValue(value)}
                    </text>
                )
            })}
        </>
    )
}

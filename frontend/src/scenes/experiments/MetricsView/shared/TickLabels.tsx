import { COLORS } from './colors'
import { formatTickValue } from './utils'

interface TickLabelsProps {
    tickValues: number[]
    scale: (value: number) => number
    y: number
    fontSize?: number
    fontWeight?: string | number
    textColor?: string
    textAnchor?: 'start' | 'middle' | 'end'
    dominantBaseline?: 'auto' | 'middle' | 'hanging'
}

/**
 * Renders tick labels for experiment charts.
 * Uses formatTickValue to display percentages with appropriate precision.
 */
export function TickLabels({
    tickValues,
    scale,
    y,
    fontSize = 9,
    fontWeight = '600',
    textColor = COLORS.TICK_TEXT_COLOR,
    textAnchor = 'middle',
    dominantBaseline = 'middle',
}: TickLabelsProps): JSX.Element {
    return (
        <>
            {tickValues.map((value) => {
                const x = scale(value)
                return (
                    <text
                        key={`text-${value}`}
                        x={x}
                        y={y}
                        textAnchor={textAnchor}
                        dominantBaseline={dominantBaseline}
                        fontSize={fontSize}
                        fill={textColor}
                        fontWeight={fontWeight}
                    >
                        {formatTickValue(value)}
                    </text>
                )
            })}
        </>
    )
}

import { COLORS } from './colors'
import { formatTickValue } from './utils'

interface TickPanelProps {
    tickValues: number[]
    valueToX: (value: number) => number
    viewBoxWidth: number
    tickPanelHeight: number
}

export function TickPanel({ tickValues, valueToX, viewBoxWidth, tickPanelHeight }: TickPanelProps): JSX.Element {
    const TICK_FONT_SIZE = 9

    return (
        <svg
            viewBox={`0 0 ${viewBoxWidth} ${tickPanelHeight}`}
            preserveAspectRatio="xMidYMid meet"
            className="ml-12 max-w-[1000px]"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ minHeight: `${tickPanelHeight}px` }} // Dynamic height based on panel configuration
        >
            {tickValues.map((value, index) => {
                const x = valueToX(value)
                return (
                    <g key={index}>
                        <text
                            x={x}
                            y={tickPanelHeight / 2}
                            textAnchor="middle"
                            dominantBaseline="middle"
                            fontSize={TICK_FONT_SIZE}
                            fill={COLORS.TICK_TEXT_COLOR}
                            fontWeight="600"
                        >
                            {formatTickValue(value)}
                        </text>
                    </g>
                )
            })}
        </svg>
    )
}

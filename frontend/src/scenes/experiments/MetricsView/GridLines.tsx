import { COLORS } from './colors'

interface GridLinesProps {
    tickValues: number[]
    valueToX: (value: number) => number
    height: number
}

export function GridLines({ tickValues, valueToX, height }: GridLinesProps): JSX.Element {
    return (
        <>
            {tickValues.map((value, index) => {
                const x = valueToX(value)
                return (
                    <line
                        key={index}
                        x1={x}
                        y1={0}
                        x2={x}
                        y2={height}
                        stroke={value === 0 ? COLORS.ZERO_LINE : COLORS.BOUNDARY_LINES}
                        strokeWidth={value === 0 ? 1 : 0.5}
                    />
                )
            })}
        </>
    )
}

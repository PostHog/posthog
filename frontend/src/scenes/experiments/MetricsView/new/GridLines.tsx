import { COLORS } from '../shared/colors'
import { valueToXCoordinate } from '../shared/utils'
import { SVG_EDGE_MARGIN, VIEW_BOX_WIDTH } from './constants'

export function GridLines({
    tickValues,
    chartRadius,
    chartHeight,
}: {
    tickValues: number[]
    chartRadius: number
    chartHeight: number
}): JSX.Element {
    return (
        <>
            {tickValues.map((value) => {
                const x = valueToXCoordinate(value, chartRadius, VIEW_BOX_WIDTH, SVG_EDGE_MARGIN)
                return (
                    <line
                        key={value}
                        x1={x}
                        y1={0}
                        x2={x}
                        y2={chartHeight}
                        stroke={value === 0 ? COLORS.ZERO_LINE : COLORS.BOUNDARY_LINES}
                        strokeWidth={value === 0 ? 1 : 0.5}
                    />
                )
            })}
        </>
    )
}

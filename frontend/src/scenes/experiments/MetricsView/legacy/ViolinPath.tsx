import { useChartColors } from '../shared/colors'
import { generateViolinPath } from './violinUtils'

interface ViolinPathProps {
    variant: {
        key: string
        [key: string]: any
    }
    x1: number
    x2: number
    y: number
    height: number
    deltaX: number
    displayOrder: number
    isSecondary: boolean
}

export function ViolinPath({
    variant,
    x1,
    x2,
    y,
    height,
    deltaX,
    displayOrder,
    isSecondary,
}: ViolinPathProps): JSX.Element {
    const colors = useChartColors()
    const CONVERSION_RATE_RECT_WIDTH = 2

    return (
        <>
            {variant.key === 'control' ? (
                // Control variant - dashed violin
                <path
                    d={generateViolinPath(x1, x2, y, height, deltaX)}
                    fill={colors.BAR_CONTROL}
                    stroke={colors.BOUNDARY_LINES}
                    strokeWidth={1}
                    strokeDasharray="2,2"
                />
            ) : (
                // Test variants - single violin with gradient fill
                <>
                    <defs>
                        <linearGradient
                            id={`gradient-${displayOrder}-${variant.key}-${isSecondary ? 'secondary' : 'primary'}`}
                            x1="0"
                            x2="1"
                            y1="0"
                            y2="0"
                        >
                            {x1 < 0 && x2 > 0 ? (
                                <>
                                    <stop offset="0%" stopColor={colors.BAR_NEGATIVE} />
                                    <stop offset={`${(-x1 / (x2 - x1)) * 100}%`} stopColor={colors.BAR_NEGATIVE} />
                                    <stop offset={`${(-x1 / (x2 - x1)) * 100}%`} stopColor={colors.BAR_POSITIVE} />
                                    <stop offset="100%" stopColor={colors.BAR_POSITIVE} />
                                </>
                            ) : (
                                <stop offset="100%" stopColor={x2 <= 0 ? colors.BAR_NEGATIVE : colors.BAR_POSITIVE} />
                            )}
                        </linearGradient>
                    </defs>
                    <path
                        d={generateViolinPath(x1, x2, y, height, deltaX)}
                        fill={`url(#gradient-${displayOrder}-${variant.key}-${isSecondary ? 'secondary' : 'primary'})`}
                    />
                </>
            )}

            {/* Delta marker */}
            <g transform={`translate(${deltaX}, 0)`}>
                <line
                    x1={0}
                    y1={y}
                    x2={0}
                    y2={y + height}
                    stroke={variant.key === 'control' ? colors.BAR_MIDDLE_POINT_CONTROL : colors.BAR_MIDDLE_POINT}
                    strokeWidth={CONVERSION_RATE_RECT_WIDTH}
                    vectorEffect="non-scaling-stroke"
                    shapeRendering="crispEdges"
                />
            </g>
        </>
    )
}

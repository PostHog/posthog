interface DotMatrixSymbolProps {
    value: number
    thresholds: number[]
    color: string
    cx?: number
    cy?: number
    firstUse?: boolean
}

export function DotMatrixSymbol({
    value,
    thresholds,
    color,
    cx = 8.5,
    cy = 8.5,
    firstUse = false,
}: DotMatrixSymbolProps): JSX.Element {
    return (
        <>
            {Number.isFinite(value) &&
                thresholds[0] !== undefined &&
                value >= thresholds[0] &&
                (firstUse ? (
                    <polygon
                        points="0,-5 1.5,-1.5 5,-1.5 2,1 3,5 0,2.7 -3,5 -2,1 -5,-1.5 -1.5,-1.5"
                        transform={`translate(${cx} ${cy})`}
                        fill={color}
                    />
                ) : (
                    <circle cx={cx} cy={cy} r={2.6} fill={color} />
                ))}
            {Number.isFinite(value) && thresholds[1] !== undefined && value >= thresholds[1] && (
                <circle cx={cx} cy={cy} r={4.4} fill="none" stroke={color} strokeWidth={1.2} />
            )}
            {Number.isFinite(value) && thresholds[2] !== undefined && value >= thresholds[2] && (
                <circle cx={cx} cy={cy} r={6.7} fill="none" stroke={color} strokeWidth={1.2} />
            )}
        </>
    )
}

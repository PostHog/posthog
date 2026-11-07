interface DotMatrixSymbolProps {
    value: number
    thresholds: number[]
    color: string
    cx?: number
    cy?: number
}

export function DotMatrixSymbol({ value, thresholds, color, cx = 8.5, cy = 8.5 }: DotMatrixSymbolProps): JSX.Element {
    return (
        <>
            {Number.isFinite(value) && thresholds[0] !== undefined && value >= thresholds[0] && (
                <circle cx={cx} cy={cy} r={2.6} fill={color} />
            )}
            {Number.isFinite(value) && thresholds[1] !== undefined && value >= thresholds[1] && (
                <circle cx={cx} cy={cy} r={4.4} fill="none" stroke={color} strokeWidth={1.2} />
            )}
            {Number.isFinite(value) && thresholds[2] !== undefined && value >= thresholds[2] && (
                <circle cx={cx} cy={cy} r={6.7} fill="none" stroke={color} strokeWidth={1.2} />
            )}
        </>
    )
}

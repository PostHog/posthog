import { LEGACY_COLORS } from './legacyColors'

interface LegacyGridLinesProps {
    tickValues: number[]
    valueToX: (value: number) => number
    height: number
}

/**
 * @deprecated
 * This component supports legacy experiment metrics.
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyGridLines({ tickValues, valueToX, height }: LegacyGridLinesProps): JSX.Element {
    return (
        <>
            {tickValues.map((value) => {
                const x = valueToX(value)
                return (
                    <line
                        key={value}
                        x1={x}
                        y1={0}
                        x2={x}
                        y2={height}
                        stroke={value === 0 ? LEGACY_COLORS.ZERO_LINE : LEGACY_COLORS.BOUNDARY_LINES}
                        strokeWidth={value === 0 ? 1 : 0.5}
                    />
                )
            })}
        </>
    )
}

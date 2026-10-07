import type { IconProps } from '@phosphor-icons/react'

const SQUARES = [
    { x: 40, y: 40 },
    { x: 136, y: 40 },
    { x: 40, y: 136 },
    { x: 136, y: 136 },
] as const

/** The rail's Spaces mark, drawn on Phosphor's 256 grid so it sits beside the Phosphor rail icons. */
export function TodaySpacesIcon({ size = 16, weight, ...props }: IconProps): JSX.Element {
    const filled = weight === 'fill'

    return (
        <svg viewBox="0 0 256 256" width={size} height={size} fill="none" role="presentation" {...props}>
            {SQUARES.map(({ x, y }) =>
                filled ? (
                    <rect key={`${x}-${y}`} x={x} y={y} width={80} height={80} rx={20} fill="currentColor" />
                ) : (
                    <rect
                        key={`${x}-${y}`}
                        x={x + 8}
                        y={y + 8}
                        width={64}
                        height={64}
                        rx={12}
                        stroke="currentColor"
                        strokeWidth={16}
                    />
                )
            )}
        </svg>
    )
}

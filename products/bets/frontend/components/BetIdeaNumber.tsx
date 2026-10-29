import type { CSSProperties } from 'react'

export function BetIdeaNumber({
    number,
    won = false,
    className = '',
    style,
}: {
    number: number | null
    won?: boolean
    className?: string
    style?: CSSProperties
}): JSX.Element {
    return (
        <span
            className={`BetIdeaNumber tabular-nums ${className}`}
            style={style}
            data-won={won || undefined}
            data-empty={number === null || undefined}
            aria-hidden
        >
            {number}
        </span>
    )
}

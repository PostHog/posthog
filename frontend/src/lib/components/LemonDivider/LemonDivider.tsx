import clsx from 'clsx'
import React from 'react'
import './LemonDivider.scss'

export interface LemonDividerProps {
    /** Twice the default amount of margin. */
    large?: boolean
    /** Whether the divider should be vertical (for separating left-to-right) instead of horizontal (top-to-bottom). */
    vertical?: boolean
    style?: React.CSSProperties
}

/** A separator ideal for being sandwiched between LemonRows.
 *
 * Horizontal by default but can be used in vertical form too.
 */
export function LemonDivider({ large = false, vertical = false, style }: LemonDividerProps): JSX.Element {
    return (
        <div
            className={clsx('LemonDivider', large && 'LemonDivider--large', vertical && 'LemonDivider--vertical')}
            style={style}
        />
    )
}

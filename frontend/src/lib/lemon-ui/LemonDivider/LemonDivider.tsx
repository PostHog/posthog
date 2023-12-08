import './LemonDivider.scss'

import clsx from 'clsx'
import { ReactNode } from 'react'

export interface LemonDividerProps {
    /** 3x the thickness of the line. */
    thick?: boolean
    /** Whether the divider should be vertical (for separating left-to-right) instead of horizontal (top-to-bottom). */
    vertical?: boolean
    /** Whether the divider should be a dashed line. */
    dashed?: boolean
    /** Adding a className will remove the default margin class names, allowing the greatest flexibility */
    className?: string
    /* The position of title inside divider */
    orientation?: 'left' | 'right' | 'center'
    /* The wrapped title */
    children?: ReactNode
}

/** A line separator for separating rows of content
 *
 * Horizontal by default but can be used in vertical form too.
 * Default padding is `m-2` (e.g. 0.5rem) and can be overridden with `className`
 */
export function LemonDivider({
    children,
    className,
    dashed = false,
    orientation = 'center',
    thick = false,
    vertical = false,
}: LemonDividerProps): JSX.Element {
    return (
        <div
            className={clsx(
                'LemonDivider',
                children && `LemonDivider--orientation-${orientation}`,
                vertical && 'LemonDivider--vertical',
                thick && 'LemonDivider--thick',
                dashed && 'LemonDivider--dashed',
                // If no className is provided we set some sensible default margins
                !className && (vertical ? 'm-2' : 'my-2'),
                className
            )}
            role="separator"
        >
            {children && children}
        </div>
    )
}

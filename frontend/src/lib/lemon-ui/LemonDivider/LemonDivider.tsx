import './LemonDivider.scss'

import clsx from 'clsx'

export interface LemonDividerProps {
    /** 3x the thickness of the line. */
    thick?: boolean
    /** Whether the divider should be vertical (for separating left-to-right) instead of horizontal (top-to-bottom). */
    vertical?: boolean
    /** Whether the divider should be a dashed line. */
    dashed?: boolean
    /** Adding a className will remove the default margin class names, allowing the greatest flexibility */
    className?: string
}

/** A line separator for separating rows of content
 *
 * Horizontal by default but can be used in vertical form too.
 * Default padding is `m-2` (e.g. 0.5rem) and can be overridden with `className`
 */
export function LemonDivider({
    vertical = false,
    dashed = false,
    thick = false,
    className,
}: LemonDividerProps): JSX.Element {
    return (
        <div
            className={clsx(
                'LemonDivider',
                vertical && 'LemonDivider--vertical',
                thick && 'LemonDivider--thick',
                dashed && 'LemonDivider--dashed',
                // If no className is provided we set some sensible default margins
                !className && (vertical ? 'm-2' : 'my-2'),
                className
            )}
            role="separator"
        />
    )
}

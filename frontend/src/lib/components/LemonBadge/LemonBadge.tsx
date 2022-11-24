import clsx from 'clsx'
import { compactNumber, humanFriendlyNumber } from 'lib/utils'
import { CSSTransition } from 'react-transition-group'
import './LemonBadge.scss'

export interface LemonBadgeProps {
    count?: number
    size?: 'small' | 'medium' | 'large'
    position?: 'none' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
    /** Maximum number of digits shown at once. Default value: 1 (so all numbers above 9 are shown as "9+"). */
    maxDigits?: number
    showZero?: boolean
    className?: string
    status?: 'primary' | 'danger' | 'muted'
    style?: React.CSSProperties
}

/** An icon-sized badge for displaying a count.
 *
 * Numbers up to 9 are displayed in full, in integer form, with 9+ for higher values.
 * JSX elements are rendered outright to support use cases where the badge is meant to show an icon.
 * If `showZero` is set to `true`, the component won't be hidden if the count is 0.
 */
export function LemonBadge({
    count,
    size = 'medium',
    position = 'none',
    maxDigits = 1,
    showZero = false,
    className,
    status = 'primary',
    ...spanProps
}: LemonBadgeProps): JSX.Element {
    // NOTE: We use 1 for the text if not showing so the fade out animation looks right
    const text =
        typeof count === 'number' && count !== 0
            ? count < Math.pow(10, maxDigits)
                ? compactNumber(count)
                : `${'9'.repeat(maxDigits)}+`
            : showZero
            ? '0'
            : '1'
    const hide = count === undefined || (count == 0 && !showZero)

    return (
        <CSSTransition in={!hide} timeout={150} classNames="LemonBadge-" mountOnEnter unmountOnExit>
            <span
                className={clsx(
                    'LemonBadge',
                    `LemonBadge--${size}`,
                    `LemonBadge--${status}`,
                    `LemonBadge--position-${position}`,
                    className
                )}
                title={typeof count === 'number' ? humanFriendlyNumber(count) : undefined}
                {...spanProps}
            >
                {text}
            </span>
        </CSSTransition>
    )
}

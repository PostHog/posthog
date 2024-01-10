import './LemonBadge.scss'

import clsx from 'clsx'
import { compactNumber, humanFriendlyNumber } from 'lib/utils'
import { CSSTransition } from 'react-transition-group'

interface LemonBadgePropsBase {
    size?: 'small' | 'medium' | 'large'
    position?: 'none' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
    className?: string
    status?: 'primary' | 'success' | 'warning' | 'danger' | 'muted' | 'data'
    active?: boolean
    style?: React.CSSProperties
    title?: string
}

export interface LemonBadgeProps extends LemonBadgePropsBase {
    content?: string | JSX.Element
    visible?: boolean
}

export interface LemonBadgeNumberProps extends LemonBadgePropsBase {
    count: number
    /** Maximum number of digits shown at once. Default value: 1 (so all numbers above 9 are shown as "9+"). */
    maxDigits?: number
    showZero?: boolean
}

/** An icon-sized badge. */
export function LemonBadge({
    content,
    visible = true,
    size = 'medium',
    position = 'none',
    className,
    status = 'primary',
    active = false,
    ...spanProps
}: LemonBadgeProps): JSX.Element {
    return (
        <CSSTransition in={visible} timeout={150} classNames="LemonBadge-" mountOnEnter unmountOnExit>
            <span
                className={clsx(
                    'LemonBadge',
                    !content && 'LemonBadge--dot',
                    `LemonBadge--${size}`,
                    `LemonBadge--${status}`,
                    `LemonBadge--position-${position}`,
                    active && 'LemonBadge--active',
                    className
                )}
                {...spanProps}
            >
                {content}
            </span>
        </CSSTransition>
    )
}

/** An icon-sized badge for displaying a count.
 *
 * Numbers up to 9 are displayed in full, in integer form, with 9+ for higher values.
 * JSX elements are rendered outright to support use cases where the badge is meant to show an icon.
 * If `showZero` is set to `true`, the component won't be hidden if the count is 0.
 */
function LemonBadgeNumber({
    count,
    maxDigits = 1,
    showZero = false,
    ...badgeProps
}: LemonBadgeNumberProps): JSX.Element {
    if (maxDigits < 1) {
        throw new Error('maxDigits must be at least 1')
    }

    // NOTE: We use 1 for the text if not showing so the fade out animation looks right
    const text =
        typeof count === 'object'
            ? count
            : typeof count === 'number' && count !== 0
            ? count < Math.pow(10, maxDigits)
                ? compactNumber(count)
                : `${'9'.repeat(maxDigits)}+`
            : showZero
            ? '0'
            : '1'
    const hide = count === undefined || (count == 0 && !showZero)

    return (
        <LemonBadge
            visible={!hide}
            title={typeof count === 'number' ? humanFriendlyNumber(count) : undefined}
            content={text}
            {...badgeProps}
        />
    )
}

LemonBadge.Number = LemonBadgeNumber

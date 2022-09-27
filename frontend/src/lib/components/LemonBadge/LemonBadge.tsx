import clsx from 'clsx'
import React from 'react'
import { CSSTransition } from 'react-transition-group'
import './LemonBadge.scss'

export interface LemonBadgeProps {
    count?: number | JSX.Element
    size?: 'small' | 'medium' | 'large'
    position?: 'none' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
    showZero?: boolean
    borderless?: boolean
    className?: string
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
    showZero = false,
    className,
    ...spanProps
}: LemonBadgeProps): JSX.Element {
    // NOTE: We use 1 for the text if not showing so the fade out animation looks right
    const text =
        typeof count === 'object'
            ? count
            : typeof count === 'number' && count !== 0
            ? count < 10
                ? String(count)
                : '9+'
            : showZero
            ? '0'
            : '1'
    const hide = count === undefined || (count == 0 && !showZero)

    return (
        <CSSTransition in={!hide} timeout={150} classNames="LemonBadge-" mountOnEnter unmountOnExit>
            <span
                className={clsx('LemonBadge', `LemonBadge--${size}`, `LemonBadge--position-${position}`, className)}
                title={String(count)}
                {...spanProps}
            >
                {text}
            </span>
        </CSSTransition>
    )
}

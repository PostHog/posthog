import clsx from 'clsx'
import React from 'react'
import { CSSTransition } from 'react-transition-group'
import './LemonBubble.scss'

export interface LemonBubbleProps {
    count?: number
    size?: 'small' | 'medium' | 'large'
    position?: 'none' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
    showZero?: boolean | JSX.Element
    borderless?: boolean
    className?: string
    style?: React.CSSProperties
}

/** An icon-sized Bubble for displaying a count.
 *
 * Numbers up to 9 are displayed in full, in integer form, with 9+ for higher values.
 * If `showZero` is set to `true`, the component won't be hidden if the count is 0.
 * If it's set to a JSX element though, that element will be shown instead of 0.
 */
export function LemonBubble({
    count,
    size = 'medium',
    position = 'none',
    showZero = false,
    className,
    ...spanProps
}: LemonBubbleProps): JSX.Element {
    const zeroDisplay = typeof showZero === 'boolean' ? '0' : showZero
    // NOTE: We use 1 for the text if not showing so the fade out animation looks right
    const text =
        typeof count === 'number' && count !== 0 ? (count < 10 ? String(count) : '9+') : showZero ? zeroDisplay : '1'
    const hide = count === undefined || (count == 0 && !showZero)

    return (
        <CSSTransition in={!hide} timeout={150} classNames="LemonBubble-" mountOnEnter unmountOnExit>
            <span
                className={clsx('LemonBubble', `LemonBubble--${size}`, `LemonBubble--position-${position}`, className)}
                title={String(count)}
                {...spanProps}
            >
                {text}
            </span>
        </CSSTransition>
    )
}

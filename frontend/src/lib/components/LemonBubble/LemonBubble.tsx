import clsx from 'clsx'
import React from 'react'
import { CSSTransition } from 'react-transition-group'
import './LemonBubble.scss'

export interface LemonBubbleProps {
    count?: number
    size?: 'small' | 'medium' | 'large'
    position?: 'none' | 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
    showZero?: boolean
}

/** An icon-sized LemonBubble.
 *
 * When given a string, the initial letter is shown. Numbers up to 99 are displayed in full, in integer form.
 */
export function LemonBubble({
    count,
    size = 'medium',
    position = 'none',
    showZero = false,
}: LemonBubbleProps): JSX.Element {
    // NOTE: We use 1 for the text
    const text = typeof count === 'number' && count > 0 ? (count < 10 ? String(count) : '9+') : '1'

    const hide = count === undefined || (count == 0 && !showZero)

    return (
        <CSSTransition in={!hide} timeout={250} classNames="anim-" mountOnEnter unmountOnExit>
            <div
                className={clsx('LemonBubble', `LemonBubble--${size}`, `LemonBubble--position-${position}`)}
                title={String(count)}
            >
                {text}
            </div>
        </CSSTransition>
    )
}

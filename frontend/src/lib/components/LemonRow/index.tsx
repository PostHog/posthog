import React from 'react'
import clsx from 'clsx'
import './LemonRow.scss'

export interface LemonRowProps<T extends keyof JSX.IntrinsicElements> extends React.HTMLProps<React.HTMLAttributes<T>> {
    icon?: React.ReactElement
    tag?: T
    status?: 'success' | 'warning' | 'danger' // CSS variable colors
    fullWidth?: boolean
}

/** Generic UI row component. Can be exploited as a button (see LemonButton) or just as a presentation element. */
export function LemonRow<T extends keyof JSX.IntrinsicElements = 'div'>({
    children,
    icon,
    className,
    tag,
    status,
    fullWidth = false,
    ...props
}: LemonRowProps<T>): JSX.Element {
    return React.createElement(
        tag || 'div',
        {
            className: clsx(
                'LemonRow',
                className,
                status && `LemonRow--status-${status}`,
                fullWidth && 'LemonRow--full-width'
            ),
            ...props,
        },
        icon ? (
            <>
                <span className="LemonRow__icon">{icon}</span>
                {children}
            </>
        ) : (
            children
        )
    )
}

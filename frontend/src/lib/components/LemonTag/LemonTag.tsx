import clsx from 'clsx'
import React from 'react'
import './LemonTag.scss'

interface LemonTagProps extends React.HTMLAttributes<HTMLDivElement> {
    type?: 'warning' | 'danger' | 'success' | 'default'
    children: JSX.Element | string
}

export function LemonTag({ type = 'default', children, className, ...props }: LemonTagProps): JSX.Element {
    return (
        <div className={clsx('lemon-tag', type, className)} {...props}>
            {children}
        </div>
    )
}

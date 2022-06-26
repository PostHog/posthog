import clsx from 'clsx'
import React from 'react'
import './LemonTag.scss'

export type LemonTagPropsType = 'highlight' | 'warning' | 'danger' | 'success' | 'default'
interface LemonTagProps extends React.HTMLAttributes<HTMLDivElement> {
    type?: LemonTagPropsType
    children: JSX.Element | string
    icon?: JSX.Element
}

export function LemonTag({ type = 'default', children, className, icon, ...props }: LemonTagProps): JSX.Element {
    return (
        <div className={clsx('lemon-tag', type, className)} {...props}>
            {icon && <span className="lemon-tag__icon">{icon}</span>}
            {children}
        </div>
    )
}

import clsx from 'clsx'
import React from 'react'
import { IconClose, IconEllipsis } from '../icons'
import { LemonButton, LemonButtonWithPopup } from '../LemonButton'
import { LemonButtonPopup } from '../LemonButton/LemonButton'
import './LemonTag.scss'

export type LemonTagPropsType = 'highlight' | 'warning' | 'danger' | 'success' | 'default'
interface LemonTagProps extends React.HTMLAttributes<HTMLDivElement> {
    type?: LemonTagPropsType
    children: JSX.Element | string
    icon?: JSX.Element
    closable?: boolean
    onClose?: () => void
    popup?: LemonButtonPopup
}

export function LemonTag({
    type = 'default',
    children,
    className,
    icon,
    closable,
    onClose,
    popup,
    ...props
}: LemonTagProps): JSX.Element {
    return (
        <div className={clsx('LemonTag', type, className)} {...props}>
            {icon && <span className="LemonTag__icon">{icon}</span>}
            {children}
            {popup?.overlay && (
                <LemonButtonWithPopup
                    popup={popup}
                    status="stealth"
                    size="small"
                    className="LemonTag__right-button"
                    icon={<IconEllipsis />}
                />
            )}
            {closable && (
                <LemonButton onClick={onClose} status="primary" size="small" className="LemonTag__right-button">
                    <IconClose />
                </LemonButton>
            )}
        </div>
    )
}

import React from 'react'
import './AlertMessage.scss'
import { IconClose, IconInfo, IconWarning } from '../icons'
import clsx from 'clsx'
import { LemonButton } from '../LemonButton'

export interface AlertMessageProps {
    type: 'info' | 'warning' | 'error' | 'success'
    /** If onClose is provided, a close button will be shown and this callback will be fired when it's clicked. */
    onClose?: () => void
    children: React.ReactChild | React.ReactChild[]
    className?: string
}

/** Generic alert message. */
export function AlertMessage({ type, onClose, children, className }: AlertMessageProps): JSX.Element {
    return (
        <div className={clsx('AlertMessage', `AlertMessage--${type}`, className)}>
            {type === 'warning' || type === 'error' ? <IconWarning /> : <IconInfo />}
            <div className="flex-1">{children}</div>
            {onClose && (
                <LemonButton status="primary-alt" size="small" icon={<IconClose />} onClick={() => onClose()} />
            )}
        </div>
    )
}

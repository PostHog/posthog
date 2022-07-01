import React from 'react'
import './AlertMessage.scss'
import { WarningOutlined } from '@ant-design/icons'
import { IconClose, IconInfo } from '../icons'
import clsx from 'clsx'
import { LemonButton } from '../LemonButton'

export interface AlertMessageProps {
    type: 'info' | 'warning' | 'error'
    /** If onClose is provided, a close button will be shown and this callback will be fired when it's clicked. */
    onClose?: () => void
    children: React.ReactChild | React.ReactChild[]
    style?: React.CSSProperties
}

/** Generic alert message. */
export function AlertMessage({ type, onClose, children, style }: AlertMessageProps): JSX.Element {
    return (
        <div className={clsx('AlertMessage', type)} style={style}>
            <div className="AlertMessage__icon">
                {type === 'warning' || type === 'error' ? <WarningOutlined /> : <IconInfo />}
            </div>
            <div className="AlertMessage__text">{children}</div>
            {onClose && (
                <LemonButton type="tertiary" className="ml-05" icon={<IconClose />} onClick={() => onClose()} />
            )}
        </div>
    )
}

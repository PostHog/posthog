import React from 'react'
import './AlertMessage.scss'
import { WarningOutlined } from '@ant-design/icons'
import { IconInfo } from '../icons'
import clsx from 'clsx'

export interface AlertMessageProps {
    type: 'info' | 'warning' | 'error'
    children: string | JSX.Element
    style?: React.CSSProperties
}

/** Generic alert message. */
export function AlertMessage({ type, children, style }: AlertMessageProps): JSX.Element {
    return (
        <div className={clsx('AlertMessage', type)} style={style}>
            <div className="AlertMessage__icon">
                {type === 'warning' || type === 'error' ? <WarningOutlined /> : <IconInfo />}
            </div>
            <div>{children}</div>
        </div>
    )
}

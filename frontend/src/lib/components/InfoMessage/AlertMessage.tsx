import React from 'react'
import './AlertMessage.scss'
import { InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import clsx from 'clsx'

export interface AlertMessageInterface {
    children: string | JSX.Element
    style?: React.CSSProperties
    type?: 'info' | 'warning'
}

/** Generic alert message. Substitutes Ant's `Alert` component. */
export function AlertMessage({ children, style, type = 'info' }: AlertMessageInterface): JSX.Element {
    return (
        <div className={clsx('lemon-alert-message', type)} style={style}>
            {type === 'warning' ? <WarningOutlined /> : <InfoCircleOutlined />}
            <div>{children}</div>
        </div>
    )
}

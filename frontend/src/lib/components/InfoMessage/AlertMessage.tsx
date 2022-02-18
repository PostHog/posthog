import React from 'react'
import './AlertMessage.scss'
import { WarningOutlined } from '@ant-design/icons'
import { IconInfo } from '../icons'
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
            <div className="lemon-alert-message__icon"> {type === 'warning' ? <WarningOutlined /> : <IconInfo />}</div>
            <div>{children}</div>
        </div>
    )
}

import React from 'react'
import './InfoMessage.scss'
import { InfoCircleOutlined } from '@ant-design/icons'

/** An informative message. */
export function InfoMessage({
    children,
    style,
}: {
    children: string | JSX.Element
    style?: React.CSSProperties
}): JSX.Element {
    return (
        <div className="info-message" style={style}>
            <InfoCircleOutlined />
            <div>{children}</div>
        </div>
    )
}

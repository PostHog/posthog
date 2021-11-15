import React from 'react'
import './InfoMessage.scss'
import { InfoCircleOutlined } from '@ant-design/icons'

// New UI for inline info messages
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
            {children}
        </div>
    )
}

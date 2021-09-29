import React from 'react'
import './ErrorMessage.scss'
import { ExclamationCircleFilled } from '@ant-design/icons'

// New UI for inline error messages
export function ErrorMessage({
    children,
    style,
}: {
    children: string | JSX.Element
    style?: React.CSSProperties
}): JSX.Element {
    return (
        <div className="error-message" style={style}>
            <ExclamationCircleFilled />
            {children}
        </div>
    )
}

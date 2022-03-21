import { CloseOutlined } from '@ant-design/icons'
import React from 'react'

export function CloseButton(props: Record<string, any>): JSX.Element {
    return (
        <span {...props} className={'btn-close cursor-pointer ' + (props.className ?? '')} style={{ ...props.style }}>
            <CloseOutlined />
        </span>
    )
}

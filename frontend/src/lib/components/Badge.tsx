import React from 'react'
import { CheckOutlined } from '@ant-design/icons'
import { Tooltip } from 'antd'

interface BadgeProps {
    icon?: JSX.Element
    type?: 'success' | 'warning' | 'danger'
    className?: string
    onClick?: () => void
    tooltip?: string
}

export function Badge({ icon, type, className, onClick, tooltip }: BadgeProps): JSX.Element {
    const getTypeIcon = (): JSX.Element | undefined => {
        if (type === 'success') {
            return <CheckOutlined />
        }
    }

    return (
        <Tooltip title={tooltip} color={type ? `var(--${type})` : undefined}>
            <div
                className={`badge${className ? ` ${className}` : ''}${onClick ? ' cursor-pointer' : ''}`}
                style={type ? { backgroundColor: `var(--${type})` } : {}}
                onClick={onClick}
            >
                {icon || getTypeIcon()}
            </div>
        </Tooltip>
    )
}

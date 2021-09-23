import React, { useMemo } from 'react'
import { CheckOutlined, WarningOutlined } from '@ant-design/icons'
import { Tooltip } from 'lib/components/Tooltip'

interface BadgeProps {
    icon?: JSX.Element
    type?: 'success' | 'warning' | 'danger' | 'primary'
    className?: string
    onClick?: () => void
    tooltip?: string
}

export function Badge({ icon, type, className, onClick, tooltip, ...props }: BadgeProps): JSX.Element {
    const getTypeIcon: JSX.Element | undefined = useMemo(() => {
        // By default the badge has no icon unless it's a badge of a specific type.
        if (type === 'success') {
            return <CheckOutlined />
        } else if (type === 'warning') {
            return <WarningOutlined />
        } else if (type === 'danger') {
            return <WarningOutlined />
        }
    }, [type])

    return (
        <Tooltip title={tooltip} color={type ? `var(--${type})` : undefined} placement="top">
            <div
                className={`badge${className ? ` ${className}` : ''}${onClick ? ' cursor-pointer' : ''}`}
                style={type ? { backgroundColor: `var(--${type})` } : {}}
                onClick={onClick}
                {...props}
            >
                {icon || getTypeIcon}
            </div>
        </Tooltip>
    )
}

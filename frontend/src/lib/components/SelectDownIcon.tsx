import React from 'react'
import { DownOutlined } from '@ant-design/icons'

// Downward arrow icon with styling that mimics that of the antd Select
export const SelectDownIcon = (props: React.HTMLAttributes<HTMLSpanElement>): JSX.Element => {
    return (
        <span {...props}>
            <DownOutlined className="pl-2 text-sm opacity-50" />
        </span>
    )
}

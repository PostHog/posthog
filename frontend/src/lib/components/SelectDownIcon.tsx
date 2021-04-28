import React from 'react'
import { DownOutlined } from '@ant-design/icons'

export const SelectDownIcon = (props: React.HTMLAttributes<HTMLSpanElement>): JSX.Element => {
    return (
        <span {...props}>
            <DownOutlined
                style={{
                    paddingLeft: '0.6em',
                    fontSize: '90%',
                    opacity: 0.5,
                }}
            />
        </span>
    )
}

import React from 'react'
import { RadioOption } from 'lib/components/RadioOption'
import { CodeOutlined, RocketOutlined, UserOutlined, TeamOutlined } from '@ant-design/icons'

export const ROLES: RadioOption[] = [
    {
        key: 'engineer',
        label: 'Engineer',
        icon: <CodeOutlined />,
    },
    {
        key: 'product',
        label: 'Product Manager',
        icon: <RocketOutlined />,
    },
]

export const TEAM_SIZES: RadioOption[] = [
    {
        key: 'me',
        label: 'Just me',
        icon: <UserOutlined />,
    },
    {
        key: '1_10',
        label: '1 - 10',
        icon: <TeamOutlined />,
    },
]

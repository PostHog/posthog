import React from 'react'
import { RadioOption } from 'lib/components/RadioOption'
import { CodeOutlined, RocketOutlined } from '@ant-design/icons'

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

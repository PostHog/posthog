import React from 'react'
import { RadioSelectType } from 'lib/components/RadioSelect'
import {
    CodeOutlined,
    RocketOutlined,
    UserOutlined,
    TeamOutlined,
    ClusterOutlined,
    SmileOutlined,
    DollarOutlined,
    ToolOutlined,
    BlockOutlined,
    MessageOutlined,
} from '@ant-design/icons'

export const ROLES: RadioSelectType[] = [
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
    {
        key: 'management',
        label: 'Management',
        icon: <ClusterOutlined />,
    },

    {
        key: 'marketing',
        label: 'Marketing',
        icon: <MessageOutlined />,
    },
    {
        key: 'sales',
        label: 'Sales',
        icon: <DollarOutlined />,
    },
    {
        key: 'cx',
        label: 'Customer success',
        icon: <SmileOutlined />,
    },
    {
        key: 'ops',
        label: 'Operations',
        icon: <ToolOutlined />,
    },
    {
        key: 'other',
        label: 'Other',
        icon: <BlockOutlined />,
    },
]

export const TEAM_SIZES: RadioSelectType[] = [
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
    {
        key: '11_50',
        label: '11 - 50',
        icon: <TeamOutlined />,
    },
    {
        key: '51_100',
        label: '51 - 100',
        icon: <TeamOutlined />,
    },
    {
        key: '100_250',
        label: '100 - 250',
        icon: <TeamOutlined />,
    },
    {
        key: '250+',
        label: '250+',
        icon: <TeamOutlined />,
    },
]

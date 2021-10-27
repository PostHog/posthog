import * as React from 'react'
import * as icons from './icons'
import { Meta } from '@storybook/react'
import { Table } from 'antd'

const allIcons = Object.entries(icons).map(([key, Icon]) => ({ name: key, icon: Icon }))

export default {
    title: 'PostHog/Components/Icons',
} as Meta

export function AllIcons(): JSX.Element {
    return (
        <Table
            pagination={false}
            dataSource={allIcons}
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    dataIndex: 'name',
                    render: function RenderName(name: string) {
                        return `<${name}>`
                    },
                },
                {
                    title: 'Icon',
                    key: 'icon',
                    dataIndex: 'icon',
                    render: function RenderIcon(Icon: () => JSX.Element) {
                        return <Icon />
                    },
                },
            ]}
        />
    )
}

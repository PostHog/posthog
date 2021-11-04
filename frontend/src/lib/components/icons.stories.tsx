import * as React from 'react'
import * as icons from './icons'
import { Meta } from '@storybook/react'
import { Table } from 'antd'

const allIcons = Object.entries(icons).map(([key, Icon]) => ({ name: key, icon: Icon }))

export default {
    title: 'PostHog/Icons',
} as Meta

export function Icons(): JSX.Element {
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
                        return <code>{`<${name}/>`}</code>
                    },
                },
                {
                    title: 'Icon',
                    key: 'icon',
                    dataIndex: 'icon',
                    render: function RenderIcon(Icon: () => JSX.Element) {
                        return (
                            <span
                                style={{
                                    display: 'inline-flex',
                                    fontSize: '1.5rem',
                                    border: '1px solid var(--primary)',
                                    boxSizing: 'content-box',
                                }}
                            >
                                <Icon />
                            </span>
                        )
                    },
                },
            ]}
        />
    )
}

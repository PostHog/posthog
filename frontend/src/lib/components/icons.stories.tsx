import * as React from 'react'
import * as icons from './icons'
import { Meta } from '@storybook/react'
import { LemonTable } from './LemonTable'

interface IconDefinition {
    name: string
    icon: (...args: any[]) => JSX.Element
}

const allIcons: IconDefinition[] = Object.entries(icons).map(([key, Icon]) => ({ name: key, icon: Icon }))

export default {
    title: 'Lemon UI/Icons',
    parameters: { options: { showPanel: false } },
} as Meta

export function Icons(): JSX.Element {
    return (
        <LemonTable
            dataSource={allIcons}
            columns={[
                {
                    title: 'Name',
                    key: 'name',
                    dataIndex: 'name',
                    render: function RenderName(name) {
                        return <code>{`<${name as string} />`}</code>
                    },
                },
                {
                    title: 'Icon',
                    key: 'icon',
                    dataIndex: 'icon',
                    render: function RenderIcon(Icon) {
                        Icon = Icon as IconDefinition['icon']
                        return (
                            <span
                                style={{
                                    display: 'inline-flex',
                                    fontSize: '1.5rem',
                                    outline: '1px solid var(--primary)',
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

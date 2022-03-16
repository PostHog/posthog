import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonTable } from './LemonTable'

export default {
    title: 'DataDisplay',
    component: LemonTable,
    parameters: { options: { showPanel: true } },
    argTypes: {
        loading: {
            control: {
                type: 'boolean',
            },
        },
    },
} as ComponentMeta<typeof LemonTable>

export function LemonTable_({ loading }: { loading: boolean }): JSX.Element {
    return (
        <LemonTable
            loading={loading}
            columns={[{ title: 'Column' }]}
            dataSource={[] as Record<string, any>[]}
            pagination={{ pageSize: 10 }}
        />
    )
}

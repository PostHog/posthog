import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonTable } from './LemonTable'

export default {
    title: 'Components/Lemon Table',
    component: LemonTable,
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

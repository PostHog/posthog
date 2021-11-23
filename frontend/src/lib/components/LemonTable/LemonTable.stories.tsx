import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonTable as _LemonTable } from './LemonTable'

export default {
    title: 'PostHog/Components/LemonTable',
    component: _LemonTable,
    parameters: { options: { showPanel: true } },
    argTypes: {
        loading: {
            control: {
                type: 'boolean',
            },
        },
    },
} as ComponentMeta<typeof _LemonTable>

export function LemonTable({ loading }: { loading: boolean }): JSX.Element {
    return (
        <_LemonTable
            loading={loading}
            columns={[{ title: 'Column' }]}
            dataSource={[] as Record<string, any>[]}
            pagination={{ pageSize: 10 }}
        />
    )
}

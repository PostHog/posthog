import React from 'react'
import { ComponentMeta } from '@storybook/react'

import { LemonTable, LemonTableProps } from './LemonTable'

export default {
    title: 'Components/Lemon Table',
    component: LemonTable,
} as ComponentMeta<typeof LemonTable>

interface MockPerson {
    name: string
    occupation: string
}

export function LemonTable_(args: Omit<LemonTableProps<MockPerson>, 'dataSource' | 'columns'>): JSX.Element {
    return (
        <LemonTable
            columns={[
                { title: 'Name', dataIndex: 'name' },
                { title: 'Occupation', dataIndex: 'occupation' },
            ]}
            dataSource={
                [
                    {
                        name: 'Werner',
                        occupation: 'Engineer',
                    },
                    {
                        name: 'Ursula',
                        occupation: 'Retired',
                    },
                    {
                        name: 'Ludwig',
                        occupation: 'Painter',
                    },
                ] as MockPerson[]
            }
            {...args}
        />
    )
}

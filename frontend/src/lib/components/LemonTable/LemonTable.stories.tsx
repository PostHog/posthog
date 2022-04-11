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

export function Basic(args: Omit<LemonTableProps<MockPerson>, 'dataSource' | 'columns'>): JSX.Element {
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

interface MockFunnelSeries {
    name: string
    stepResults: [[number, number], [number, number]]
}

export function Grouped(args: Omit<LemonTableProps<MockFunnelSeries>, 'dataSource' | 'columns'>): JSX.Element {
    return (
        <LemonTable
            columns={[
                {
                    children: [
                        {
                            title: 'Breakdown',
                            dataIndex: 'name',
                        },
                    ],
                },
                {
                    title: '1. Pageview',
                    children: [
                        {
                            title: 'Completed',
                            render: (_: number, record: MockFunnelSeries) => record.stepResults[0][0],
                        },
                        {
                            title: 'Dropped off',
                            render: (_: number, record: MockFunnelSeries) => record.stepResults[0][1],
                        },
                    ],
                },
                {
                    title: '2. Signup',
                    children: [
                        {
                            title: 'Completed',
                            render: (_: number, record: MockFunnelSeries) => record.stepResults[1][0],
                        },
                        {
                            title: 'Dropped off',
                            render: (_: number, record: MockFunnelSeries) => record.stepResults[1][1],
                        },
                    ],
                },
            ]}
            dataSource={
                [
                    {
                        name: 'United States',
                        stepResults: [
                            [4325, 0],
                            [4324, 1],
                        ],
                    },
                    {
                        name: 'France',
                        stepResults: [
                            [53, 0],
                            [12, 41],
                        ],
                    },
                    {
                        name: 'Germany',
                        stepResults: [
                            [92, 0],
                            [1, 91],
                        ],
                    },
                ] as MockFunnelSeries[]
            }
            {...args}
        />
    )
}

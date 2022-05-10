import React from 'react'
import { ComponentMeta, ComponentStory } from '@storybook/react'
import { LemonTable, LemonTableProps } from './LemonTable'

export default {
    title: 'Lemon UI/Lemon Table',
    component: LemonTable,
} as ComponentMeta<typeof LemonTable>

interface MockPerson {
    name: string
    occupation: string
}

interface MockFunnelSeries {
    name: string
    stepResults: [[number, number], [number, number]]
}

// @ts-expect-error
const GroupedTemplate: ComponentStory<typeof LemonTable> = (props: LemonTableProps<MockFunnelSeries>) => {
    return (
        <LemonTable
            {...props}
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
                            render: (_, record) => record.stepResults[0][0],
                        },
                        {
                            title: 'Dropped off',
                            render: (_, record) => record.stepResults[0][1],
                        },
                    ],
                },
                {
                    title: '2. Signup',
                    children: [
                        {
                            title: 'Completed',
                            render: (_, record) => record.stepResults[1][0],
                        },
                        {
                            title: 'Dropped off',
                            render: (_, record) => record.stepResults[1][1],
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
        />
    )
}

// @ts-expect-error
const BasicTemplate: ComponentStory<typeof LemonTable> = (props: LemonTableProps<MockPerson>) => {
    return (
        <LemonTable
            {...props}
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    sorter: (a, b) => a.name.split(' ')[1].localeCompare(b.name.split(' ')[1]),
                },
                {
                    title: 'Occupation',
                    dataIndex: 'occupation',
                    sorter: (a, b) => a.occupation.localeCompare(b.occupation),
                },
            ]}
            dataSource={
                [
                    {
                        name: 'Werner C.',
                        occupation: 'Engineer',
                    },
                    {
                        name: 'Ursula Z.',
                        occupation: 'Retired',
                    },
                    {
                        name: 'Ludwig A.',
                        occupation: 'Painter',
                    },
                    {
                        name: 'Arnold S.',
                        occupation: 'Body-builder',
                    },
                    {
                        name: 'Franz B.',
                        occupation: 'Teacher',
                    },
                ] as MockPerson[]
            }
        />
    )
}

const EmptyTemplate: ComponentStory<typeof LemonTable> = (props: LemonTableProps<Record<string, any>>) => {
    return (
        <LemonTable
            {...props}
            columns={[
                { title: 'Name', dataIndex: 'name' },
                { title: 'Occupation', dataIndex: 'occupation' },
            ]}
            dataSource={[]}
        />
    )
}

export const Basic = BasicTemplate.bind({})
Basic.args = {}

export const Grouped = GroupedTemplate.bind({})
Grouped.args = {}

export const Empty = EmptyTemplate.bind({})
Empty.args = {}

export const PaginatedAutomatically = BasicTemplate.bind({})
PaginatedAutomatically.args = { nouns: ['person', 'people'], pagination: { pageSize: 3 } }

export const WithExpandableRows = BasicTemplate.bind({})
WithExpandableRows.args = {
    expandable: {
        rowExpandable: (record) => record.occupation !== 'Retired',
        expandedRowRender: function RenderCow() {
            return <img src="https://c.tenor.com/WAFH6TX2VIYAAAAC/polish-cow.gif" />
        },
    },
}

export const Small = BasicTemplate.bind({})
Small.args = { size: 'small' }

export const Embedded = BasicTemplate.bind({})
Embedded.args = { embedded: true }

export const Loading = BasicTemplate.bind({})
Loading.args = { loading: true }

export const EmptyLoading = EmptyTemplate.bind({})
EmptyLoading.args = { loading: true }

export const EmptyLoadingWithManySkeletonRows = EmptyTemplate.bind({})
EmptyLoadingWithManySkeletonRows.args = { loading: true, loadingSkeletonRows: 10 }

export const WithoutHeader = BasicTemplate.bind({})
WithoutHeader.args = { showHeader: false }

export const WithoutUppercasingInHeader = BasicTemplate.bind({})
WithoutUppercasingInHeader.args = { uppercaseHeader: false }

export const WithColorCodedRows = BasicTemplate.bind({})
WithColorCodedRows.args = {
    rowRibbonColor: ({ occupation }) =>
        occupation === 'Engineer'
            ? 'var(--success)'
            : occupation === 'Retired'
            ? 'var(--warning)'
            : occupation === 'Body-builder'
            ? 'var(--danger)'
            : null,
}

export const WithHighlightedRows = BasicTemplate.bind({})
WithHighlightedRows.args = {
    rowStatus: ({ occupation }) => (['Retired', 'Body-builder'].includes(occupation) ? 'highlighted' : null),
}

export const WithMandatorySorting = BasicTemplate.bind({})
WithMandatorySorting.args = { defaultSorting: { columnKey: 'name', order: 1 }, disableSortingCancellation: true }

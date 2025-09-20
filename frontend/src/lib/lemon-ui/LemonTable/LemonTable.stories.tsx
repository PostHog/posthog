import { Meta, StoryFn, StoryObj } from '@storybook/react'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { LemonButton } from '../LemonButton'
import { LemonTable, LemonTableProps } from './LemonTable'
import { LemonTableLink } from './LemonTableLink'

type Story = StoryObj<typeof LemonTable>
const meta: Meta<typeof LemonTable> = {
    title: 'Lemon UI/Lemon Table',
    component: LemonTable,
    tags: ['autodocs'],
}
export default meta

interface MockPerson {
    name: string
    occupation: string
}

interface MockFunnelSeries {
    name: string
    stepResults: [[number, number], [number, number]]
}

// @ts-expect-error
const GroupedTemplate: StoryFn<typeof LemonTable> = (props: LemonTableProps<MockFunnelSeries>) => {
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
const BasicTemplate: StoryFn<typeof LemonTable> = (props: LemonTableProps<MockPerson>) => {
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
                    tooltip: 'What they are primarily working on.',
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

const EmptyTemplate: StoryFn<typeof LemonTable> = (props: LemonTableProps<Record<string, any>>) => {
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

export const Basic: Story = BasicTemplate.bind({})
Basic.args = {}

export const Grouped: Story = GroupedTemplate.bind({})
Grouped.args = {}

export const Empty: Story = EmptyTemplate.bind({})
Empty.args = {}

export const PaginatedAutomatically: Story = BasicTemplate.bind({})
PaginatedAutomatically.args = { nouns: ['person', 'people'], pagination: { pageSize: 3 } }

export const WithExpandableRows: Story = BasicTemplate.bind({})
WithExpandableRows.args = {
    expandable: {
        rowExpandable: (record) => record.occupation !== 'Retired',
        expandedRowRender: function RenderCow() {
            return <img src="https://c.tenor.com/WAFH6TX2VIYAAAAC/polish-cow.gif" />
        },
    },
}

export const Small: Story = BasicTemplate.bind({})
Small.args = { size: 'small' }

export const Embedded: Story = BasicTemplate.bind({})
Embedded.args = { embedded: true }

export const Stealth: Story = BasicTemplate.bind({})
Stealth.args = { stealth: true }

export const Loading: Story = BasicTemplate.bind({})
Loading.args = { loading: true }
Loading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '.LemonTableLoader',
    },
}

export const EmptyLoading: Story = EmptyTemplate.bind({})
EmptyLoading.args = { loading: true }
EmptyLoading.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '.LemonTableLoader',
    },
}

export const EmptyLoadingWithManySkeletonRows: Story = EmptyTemplate.bind({})
EmptyLoadingWithManySkeletonRows.args = { loading: true, loadingSkeletonRows: 10 }
EmptyLoadingWithManySkeletonRows.parameters = {
    testOptions: {
        waitForLoadersToDisappear: false,
        waitForSelector: '.LemonTableLoader',
    },
}

export const WithoutHeader: Story = BasicTemplate.bind({})
WithoutHeader.args = { showHeader: false }

export const WithoutUppercasingInHeader: Story = BasicTemplate.bind({})
WithoutUppercasingInHeader.args = { uppercaseHeader: false }

export const WithFooter: Story = BasicTemplate.bind({})
WithFooter.args = {
    footer: (
        <>
            <div className="flex items-center m-2">
                <LemonButton center fullWidth>
                    Load more rows
                </LemonButton>
            </div>
        </>
    ),
}

export const WithColorCodedRows: Story = BasicTemplate.bind({})
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

export const WithHighlightedRows: Story = BasicTemplate.bind({})
WithHighlightedRows.args = {
    rowStatus: ({ occupation }) => (['Retired', 'Body-builder'].includes(occupation) ? 'highlighted' : null),
}

export const WithMandatorySorting: Story = BasicTemplate.bind({})
WithMandatorySorting.args = { defaultSorting: { columnKey: 'name', order: 1 }, noSortingCancellation: true }

export const WithStickyFirstColumn = (): JSX.Element => {
    useDelayedOnMountEffect(() => {
        const scrollableInner = document.querySelector(
            '#story--lemon-ui-lemon-table--with-sticky-first-column .scrollable__inner'
        )
        if (scrollableInner) {
            scrollableInner.scrollLeft = 20
        }
    })

    return (
        <LemonTable
            className="max-w-100"
            firstColumnSticky
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    sorter: (a, b) => a.name.split(' ')[1].localeCompare(b.name.split(' ')[1]),
                },
                {
                    title: 'Occupation',
                    dataIndex: 'occupation',
                    tooltip: 'What they are primarily working on.',
                    sorter: (a, b) => a.occupation.localeCompare(b.occupation),
                },
                {
                    title: 'Age',
                    key: 'age',
                    render: (_, person) => `${person.name.length * 12} years`,
                },
                {
                    title: 'Zodiac sign',
                    key: 'zodiac',
                    render: () => 'Gemini',
                },
                {
                    title: 'Favorite color',
                    key: 'color',
                    render: (_, person) => (person.occupation === 'Engineer' ? 'Blue' : 'Red'),
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

export const WithLink = (): JSX.Element => {
    return (
        <LemonTable
            columns={[
                {
                    title: 'Name',
                    dataIndex: 'name',
                    sorter: (a, b) => a.name.split(' ')[1].localeCompare(b.name.split(' ')[1]),
                    render: (_, item) => (
                        <LemonTableLink
                            title={item.name}
                            to="/test"
                            description={`${item.name} is a ${item.occupation.toLowerCase()} who is ${
                                item.name.length * 12
                            } years old.`}
                        />
                    ),
                },
                {
                    title: 'Occupation',
                    dataIndex: 'occupation',
                    tooltip: 'What they are primarily working on.',
                    sorter: (a, b) => a.occupation.localeCompare(b.occupation),
                },
                {
                    title: 'Age',
                    key: 'age',
                    render: (_, person) => `${person.name.length * 12} years`,
                },
                {
                    title: 'Zodiac sign',
                    key: 'zodiac',
                    render: () => 'Gemini',
                },
                {
                    title: 'Favorite color',
                    key: 'color',
                    render: (_, person) => (person.occupation === 'Engineer' ? 'Blue' : 'Red'),
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

import type { Meta, StoryObj } from '@storybook/react'

import { IconTrash } from '@posthog/icons'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { IconLink } from '../icons'
import { LemonButton } from '../LemonButton'
import { LemonDivider } from '../LemonDivider'
import { LemonTable, LemonTableProps } from './LemonTable'
import { LemonTableLink } from './LemonTableLink'
import { LemonTableColumns } from './types'

type Story = StoryObj<LemonTableProps<any>>
const meta: Meta<LemonTableProps<any>> = {
    title: 'Lemon UI/Lemon Table',
    component: LemonTable as any,
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

const MANY_PEOPLE: MockPerson[] = [
    { name: 'Werner C.', occupation: 'Engineer' },
    { name: 'Ursula Z.', occupation: 'Retired' },
    { name: 'Ludwig A.', occupation: 'Painter' },
    { name: 'Arnold S.', occupation: 'Body-builder' },
    { name: 'Franz B.', occupation: 'Teacher' },
    { name: 'Marie K.', occupation: 'Scientist' },
    { name: 'Hans G.', occupation: 'Architect' },
    { name: 'Greta T.', occupation: 'Activist' },
    { name: 'Otto V.', occupation: 'Musician' },
    { name: 'Helga P.', occupation: 'Doctor' },
    { name: 'Klaus M.', occupation: 'Chef' },
    { name: 'Ingrid S.', occupation: 'Writer' },
]

const WIDE_COLUMNS: LemonTableColumns<MockPerson> = [
    {
        title: 'Name',
        dataIndex: 'name',
        width: 150,
        sorter: (a, b) => a.name.split(' ')[1].localeCompare(b.name.split(' ')[1]),
    },
    {
        title: 'Occupation',
        dataIndex: 'occupation',
        width: 150,
        tooltip: 'What they are primarily working on.',
        sorter: (a, b) => a.occupation.localeCompare(b.occupation),
    },
    {
        title: 'Age',
        key: 'age',
        width: 120,
        render: (_, person) => `${person.name.length * 12} years`,
    },
    {
        title: 'Zodiac sign',
        key: 'zodiac',
        width: 120,
        render: () => 'Gemini',
    },
    {
        title: 'Favorite color',
        key: 'color',
        width: 120,
        render: (_, person) => (person.occupation === 'Engineer' ? 'Blue' : 'Red'),
    },
    {
        title: 'Hometown',
        key: 'hometown',
        width: 120,
        render: (_, person) => (person.occupation === 'Engineer' ? 'Berlin' : 'Munich'),
    },
    {
        title: 'Years of experience',
        key: 'experience',
        width: 150,
        render: (_, person) => `${person.name.length + 5} years`,
    },
]

const renderGrouped = (props: LemonTableProps<MockFunnelSeries>): JSX.Element => {
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

const renderBasic = (props: LemonTableProps<MockPerson>): JSX.Element => {
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

const renderEmpty = (props: LemonTableProps<Record<string, any>>): JSX.Element => {
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

export const Basic: Story = { render: renderBasic as any, args: {} }

export const Grouped: Story = { render: renderGrouped as any, args: {} }

export const Empty: Story = { render: renderEmpty as any, args: {} }

export const PaginatedAutomatically: Story = {
    render: renderBasic as any,
    args: { nouns: ['person', 'people'], pagination: { pageSize: 3 } },
}

export const WithExpandableRows: Story = {
    render: renderBasic as any,
    args: {
        expandable: {
            rowExpandable: (record) => record.occupation !== 'Retired',
            expandedRowRender: function RenderCow() {
                return <img src="https://c.tenor.com/WAFH6TX2VIYAAAAC/polish-cow.gif" alt="Dancing cow" />
            },
        },
    },
}

export const Small: Story = { render: renderBasic as any, args: { size: 'small' } }

export const Embedded: Story = { render: renderBasic as any, args: { embedded: true } }

export const Stealth: Story = { render: renderBasic as any, args: { stealth: true } }

export const Loading: Story = {
    render: renderBasic as any,
    args: { loading: true },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '.LemonTableLoader',
        },
    },
}

export const EmptyLoading: Story = {
    render: renderEmpty as any,
    args: { loading: true },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '.LemonTableLoader',
        },
    },
}

export const EmptyLoadingWithManySkeletonRows: Story = {
    render: renderEmpty as any,
    args: { loading: true, loadingSkeletonRows: 10 },
    parameters: {
        testOptions: {
            waitForLoadersToDisappear: false,
            waitForSelector: '.LemonTableLoader',
        },
    },
}

export const WithoutHeader: Story = { render: renderBasic as any, args: { showHeader: false } }

export const WithoutUppercasingInHeader: Story = { render: renderBasic as any, args: { uppercaseHeader: false } }

export const WithFooter: Story = {
    render: renderBasic as any,
    args: {
        footer: (
            <>
                <div className="flex items-center m-2">
                    <LemonButton center fullWidth>
                        Load more rows
                    </LemonButton>
                </div>
            </>
        ),
    },
}

export const WithColorCodedRows: Story = {
    render: renderBasic as any,
    args: {
        rowRibbonColor: ({ occupation }) =>
            occupation === 'Engineer'
                ? 'var(--success)'
                : occupation === 'Retired'
                  ? 'var(--warning)'
                  : occupation === 'Body-builder'
                    ? 'var(--danger)'
                    : null,
    },
}

export const WithHighlightedRows: Story = {
    render: renderBasic as any,
    args: {
        rowStatus: ({ occupation }) => (['Retired', 'Body-builder'].includes(occupation) ? 'highlighted' : null),
    },
}

export const WithMandatorySorting: Story = {
    render: renderBasic as any,
    args: { defaultSorting: { columnKey: 'name', order: 1 }, noSortingCancellation: true },
}

export const WithStickyFirstColumn: Story = {
    render: () => {
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
                columns={WIDE_COLUMNS.slice(0, 5)}
                dataSource={MANY_PEOPLE.slice(0, 5)}
            />
        )
    },
}

export const WithLink: Story = {
    render: () => {
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
                    ...WIDE_COLUMNS.slice(1, 5),
                ]}
                dataSource={MANY_PEOPLE.slice(0, 5)}
            />
        )
    },
}

export const WithCellActions: Story = {
    render: () => {
        return (
            <LemonTable
                columns={[
                    {
                        title: 'Name',
                        dataIndex: 'name',
                        cellActions: (value) => (
                            <>
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    icon={<IconLink />}
                                    onClick={() => alert(`Viewing profile for ${value}`)}
                                >
                                    View profile
                                </LemonButton>
                                <LemonButton fullWidth size="small" onClick={() => alert(`Copying ${value}`)}>
                                    Copy name
                                </LemonButton>
                            </>
                        ),
                    },
                    {
                        title: 'Occupation',
                        dataIndex: 'occupation',
                        cellActions: (value, record) => (
                            <>
                                <LemonButton fullWidth size="small" onClick={() => alert(`Filtering to ${value}`)}>
                                    Filter to {value}
                                </LemonButton>
                                <LemonDivider />
                                <LemonButton
                                    fullWidth
                                    size="small"
                                    status="danger"
                                    icon={<IconTrash />}
                                    onClick={() => alert(`Removing ${record.name}`)}
                                >
                                    Remove person
                                </LemonButton>
                            </>
                        ),
                    },
                    {
                        title: 'Age',
                        key: 'age',
                        render: (_, person) => `${person.name.length * 12} years`,
                    },
                ]}
                dataSource={MANY_PEOPLE.slice(0, 5)}
            />
        )
    },
}

export const WithRowActions: Story = {
    render: () => {
        return (
            <LemonTable
                columns={[
                    {
                        title: 'Name',
                        dataIndex: 'name',
                    },
                    {
                        title: 'Occupation',
                        dataIndex: 'occupation',
                    },
                    {
                        title: 'Age',
                        key: 'age',
                        render: (_, person) => `${person.name.length * 12} years`,
                    },
                ]}
                rowActions={(record) => (
                    <>
                        <LemonButton
                            fullWidth
                            size="small"
                            icon={<IconLink />}
                            onClick={() => alert(`Viewing ${record.name}'s profile`)}
                        >
                            View profile
                        </LemonButton>
                        <LemonButton fullWidth size="small" onClick={() => alert(`Editing ${record.name}`)}>
                            Edit
                        </LemonButton>
                        <LemonDivider />
                        <LemonButton
                            fullWidth
                            size="small"
                            status="danger"
                            icon={<IconTrash />}
                            onClick={() => alert(`Deleting ${record.name}`)}
                        >
                            Delete
                        </LemonButton>
                    </>
                )}
                dataSource={MANY_PEOPLE.slice(0, 5)}
            />
        )
    },
}

export const WithHorizontalOverflow: Story = {
    render: () => {
        return (
            <div className="max-w-120">
                <LemonTable columns={WIDE_COLUMNS} dataSource={MANY_PEOPLE.slice(0, 5)} />
            </div>
        )
    },
}

export const WithVerticalOverflow: Story = {
    render: () => {
        return (
            <div className="max-h-60 flex flex-col overflow-auto">
                <LemonTable columns={WIDE_COLUMNS.slice(0, 2)} dataSource={MANY_PEOPLE} />
            </div>
        )
    },
}

export const WithHorizontalAndVerticalOverflow: Story = {
    render: () => {
        return (
            <div className="max-w-120 max-h-60 flex flex-col overflow-auto">
                <LemonTable columns={WIDE_COLUMNS} dataSource={MANY_PEOPLE} />
            </div>
        )
    },
}

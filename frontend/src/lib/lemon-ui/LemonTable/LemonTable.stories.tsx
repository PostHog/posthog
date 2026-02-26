import { Meta, StoryFn, StoryObj } from '@storybook/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconTrash } from '@posthog/icons'

import { useDelayedOnMountEffect } from 'lib/hooks/useOnMountEffect'

import { IconLink } from '../icons'
import { LemonButton } from '../LemonButton'
import { LemonDivider } from '../LemonDivider'
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
            return <img src="https://c.tenor.com/WAFH6TX2VIYAAAAC/polish-cow.gif" alt="Dancing cow" />
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

export const WithCellActions = (): JSX.Element => {
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
            dataSource={
                [
                    { name: 'Werner C.', occupation: 'Engineer' },
                    { name: 'Ursula Z.', occupation: 'Retired' },
                    { name: 'Ludwig A.', occupation: 'Painter' },
                    { name: 'Arnold S.', occupation: 'Body-builder' },
                    { name: 'Franz B.', occupation: 'Teacher' },
                ] as MockPerson[]
            }
        />
    )
}

export const WithRowActions = (): JSX.Element => {
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
            dataSource={
                [
                    { name: 'Werner C.', occupation: 'Engineer' },
                    { name: 'Ursula Z.', occupation: 'Retired' },
                    { name: 'Ludwig A.', occupation: 'Painter' },
                    { name: 'Arnold S.', occupation: 'Body-builder' },
                    { name: 'Franz B.', occupation: 'Teacher' },
                ] as MockPerson[]
            }
        />
    )
}

// --- Virtualized stories ---

interface MockLogEntry {
    id: number
    timestamp: string
    level: 'info' | 'warn' | 'error' | 'debug'
    service: string
    message: string
}

const SERVICES = ['api-gateway', 'auth-service', 'billing', 'events-pipeline', 'plugin-server', 'web-app', 'worker']
const LEVELS: MockLogEntry['level'][] = ['info', 'warn', 'error', 'debug']
const MESSAGES = [
    'Request processed successfully',
    'Connection pool exhausted, waiting for available connection',
    'Failed to parse JSON payload',
    'Rate limit exceeded for client',
    'Cache miss, fetching from database',
    'Health check passed',
    'Timeout waiting for downstream service',
    'Successfully exported batch of events',
    'Retrying failed operation (attempt 3/5)',
    'Memory usage above 80% threshold',
    'Certificate renewal scheduled',
    'Database migration completed',
    'Kafka consumer lag detected',
    'Query execution time exceeded 5s',
    'Feature flag evaluated',
]

function generateLogEntries(count: number): MockLogEntry[] {
    const entries: MockLogEntry[] = []
    const baseTime = new Date('2026-02-24T18:00:00Z').getTime()
    for (let i = 0; i < count; i++) {
        entries.push({
            id: i,
            timestamp: new Date(baseTime - i * 1234).toISOString().replace('T', ' ').slice(0, 23),
            level: LEVELS[i % LEVELS.length],
            service: SERVICES[i % SERVICES.length],
            message: `${MESSAGES[i % MESSAGES.length]} [req_${(i * 7919).toString(16)}]`,
        })
    }
    return entries
}

function DomRowCounter({ tableSelector }: { tableSelector: string }): JSX.Element {
    const [count, setCount] = useState(0)
    const rafRef = useRef(0)

    const measure = useCallback(() => {
        const tbody = document.querySelector(`${tableSelector} tbody`)
        if (tbody) {
            setCount(tbody.querySelectorAll('tr:not([aria-hidden])').length)
        }
        rafRef.current = requestAnimationFrame(measure)
    }, [tableSelector])

    useEffect(() => {
        rafRef.current = requestAnimationFrame(measure)
        return () => cancelAnimationFrame(rafRef.current)
    }, [measure])

    return (
        <div className="sticky top-0 z-10 bg-warning-highlight border border-warning rounded px-3 py-1.5 text-sm font-mono mb-2">
            DOM rows: <strong>{count}</strong>
        </div>
    )
}

const LEVEL_COLORS: Record<MockLogEntry['level'], string> = {
    error: 'var(--danger)',
    warn: 'var(--warning)',
    info: 'var(--success)',
    debug: 'var(--muted)',
}

export const Virtualized = (): JSX.Element => {
    const data = useMemo(() => generateLogEntries(10_000), [])

    return (
        <div id="virtualized-story">
            <DomRowCounter tableSelector="#virtualized-story" />
            <p className="text-muted text-xs mb-2">
                10,000 rows — scroll to verify smooth performance. The DOM counter above should stay roughly constant.
            </p>
            <LemonTable<MockLogEntry>
                virtualized={{ estimatedRowHeight: 36 }}
                dataSource={data}
                rowKey="id"
                size="small"
                rowRibbonColor={(record) => LEVEL_COLORS[record.level]}
                columns={[
                    { title: '#', key: 'id', render: (_, r) => r.id, width: 60 },
                    { title: 'Timestamp', dataIndex: 'timestamp', width: 200 },
                    {
                        title: 'Level',
                        dataIndex: 'level',
                        width: 70,
                        render: (level) => (
                            <span
                                className="font-mono font-bold uppercase"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ color: LEVEL_COLORS[level as MockLogEntry['level']] }}
                            >
                                {level as string}
                            </span>
                        ),
                    },
                    { title: 'Service', dataIndex: 'service', width: 150 },
                    { title: 'Message', dataIndex: 'message' },
                ]}
            />
        </div>
    )
}

export const VirtualizedWithExpandableRows = (): JSX.Element => {
    const data = useMemo(() => generateLogEntries(10_000), [])

    return (
        <div id="virtualized-expandable-story">
            <DomRowCounter tableSelector="#virtualized-expandable-story" />
            <p className="text-muted text-xs mb-2">
                10,000 expandable rows — click a row's expand button to verify dynamic content works with
                virtualization.
            </p>
            <LemonTable<MockLogEntry>
                virtualized={{ estimatedRowHeight: 36 }}
                dataSource={data}
                rowKey="id"
                size="small"
                expandable={{
                    expandedRowRender: (record) => (
                        <div className="p-4 font-mono text-xs space-y-1">
                            <div>
                                <strong>ID:</strong> {record.id}
                            </div>
                            <div>
                                <strong>Timestamp:</strong> {record.timestamp}
                            </div>
                            <div>
                                <strong>Level:</strong> {record.level}
                            </div>
                            <div>
                                <strong>Service:</strong> {record.service}
                            </div>
                            <div>
                                <strong>Message:</strong> {record.message}
                            </div>
                            <div>
                                <strong>Stack trace:</strong>
                            </div>
                            <pre className="bg-bg-primary p-2 rounded text-xs">
                                {`at ${record.service}.handleRequest (${record.service}.ts:${record.id % 500}:12)\n` +
                                    `at Router.dispatch (router.ts:${(record.id * 3) % 200}:5)\n` +
                                    `at Server.listen (server.ts:42:8)`}
                            </pre>
                        </div>
                    ),
                }}
                columns={[
                    { title: '#', key: 'id', render: (_, r) => r.id, width: 60 },
                    { title: 'Timestamp', dataIndex: 'timestamp', width: 200 },
                    {
                        title: 'Level',
                        dataIndex: 'level',
                        width: 70,
                        render: (level) => (
                            <span
                                className="font-mono font-bold uppercase"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ color: LEVEL_COLORS[level as MockLogEntry['level']] }}
                            >
                                {level as string}
                            </span>
                        ),
                    },
                    { title: 'Service', dataIndex: 'service', width: 150 },
                    { title: 'Message', dataIndex: 'message' },
                ]}
            />
        </div>
    )
}

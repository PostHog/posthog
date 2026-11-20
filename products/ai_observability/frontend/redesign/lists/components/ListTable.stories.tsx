import type { Meta, StoryObj } from '@storybook/react'

import { LemonTableColumns } from 'lib/lemon-ui/LemonTable'

import { ListEmptyState } from './ListEmptyState'
import { ListErrorState } from './ListErrorState'
import { ListTable, ListTableProps } from './ListTable'

interface SampleRow {
    id: string
    time: string
    name: string
    person: string
    input: string
    latency: string
    cost: string
}

const ROWS: SampleRow[] = [
    {
        id: 'trace-1',
        time: '11:43',
        name: 'rag-query',
        person: 'carol@example.com',
        input: 'Can I roll back a deploy?',
        latency: '1.84s',
        cost: '<$0.001',
    },
    {
        id: 'trace-2',
        time: '11:40',
        name: 'support-reply',
        person: 'dan@example.com',
        input: 'Where do I change my billing email?',
        latency: '3.12s',
        cost: '$0.004',
    },
    {
        id: 'trace-3',
        time: '11:38',
        name: 'summarize-ticket',
        person: 'erin@example.com',
        input: 'Summarize the thread about the export bug',
        latency: '0.92s',
        cost: '$0.002',
    },
]

const COLUMNS: LemonTableColumns<SampleRow> = [
    { title: 'Time', dataIndex: 'time' },
    { title: 'Name', dataIndex: 'name' },
    { title: 'Person', dataIndex: 'person' },
    { title: 'Input', render: (_, row) => <span className="block max-w-60 truncate">{row.input}</span> },
    { title: 'Latency', dataIndex: 'latency', align: 'right' },
    { title: 'Cost', dataIndex: 'cost', align: 'right' },
]

type SampleTableProps = ListTableProps<SampleRow>

function SampleTable(props: SampleTableProps): JSX.Element {
    return <ListTable<SampleRow> {...props} />
}

const meta: Meta<typeof SampleTable> = {
    title: 'Scenes-App/AI observability/Lists/List table',
    component: SampleTable,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: {
        state: 'ready',
        columns: COLUMNS,
        rows: ROWS,
        rowKey: (row) => row.id,
        refreshing: false,
        onNext: () => {},
        emptyState: (
            <ListEmptyState
                title="No traces yet"
                description="Traces show here once your app sends its first LLM calls."
            />
        ),
        emptyFilteredState: (
            <ListEmptyState
                title="No traces match these filters"
                description="Try a wider date range, or clear the filters to see every trace."
                action={{ label: 'Clear filters', onClick: () => {}, 'data-attr': 'traces-list-clear-filters' }}
            />
        ),
        errorState: (
            <ListErrorState
                title="We couldn't load traces"
                description="Something went wrong while loading them. Try again in a moment."
                retry={{ onClick: () => {}, 'data-attr': 'traces-list-retry' }}
            />
        ),
        'data-attr': 'traces-list',
    },
}
export default meta

type Story = StoryObj<typeof SampleTable>

export const Loading: Story = { args: { state: 'loading', rows: [], onPrevious: () => {} } }

export const Ready: Story = {}

export const Refreshing: Story = { args: { refreshing: true, onPrevious: () => {} } }

export const Empty: Story = { args: { state: 'empty', rows: [], onNext: undefined } }

export const EmptyFiltered: Story = { args: { state: 'empty-filtered', rows: [], onNext: undefined } }

export const LoadFailed: Story = { args: { state: 'error', rows: [], onNext: undefined } }

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-96">
                <StoryComponent />
            </div>
        ),
    ],
}

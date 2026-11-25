import type { Meta, StoryObj } from '@storybook/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type { TraceListItemApi, TracePersonApi, TraceSentimentApi } from '../../../generated/api.schemas'
import type { TraceCellLoad } from '../../shared/cellLoads'
import { makeTraceListItem, makeTracePreview, makeUnreadTraceCells, ready } from '../testFixtures'
import { TracesTableCells, tracesTableColumns } from './TracesTableColumns'

const ITEMS: TraceListItemApi[] = [
    makeTraceListItem({
        id: 'trace-1',
        name: 'rag-query',
        createdAt: '2026-09-01T11:43:00Z',
        toolsCalled: ['search_docs', 'read_file'],
    }),
    makeTraceListItem({
        id: 'trace-2',
        name: 'chat-completion',
        createdAt: '2026-09-01T11:40:00Z',
        hasError: true,
        errorCount: 2,
        firstError: 'Context window exceeded',
        totals: {
            costUsd: 0,
            inputTokens: null,
            outputTokens: null,
            cacheReadTokens: null,
            cacheWriteTokens: null,
            latencyMs: 420,
        },
        review: {
            review: { reviewedBy: 'Ana', reviewedAt: '2026-09-01T12:00:00Z', comment: null, scores: [] },
            queue: null,
        },
    }),
    makeTraceListItem({
        id: 'trace-3',
        name: null,
        createdAt: '2026-09-01T11:38:00Z',
        isSupportTrace: true,
        totalsPartial: true,
        costAndLatencyPartial: true,
        toolsCalled: ['search_docs', 'read_file', 'run_sql', 'send_email'],
        review: { review: null, queue: { id: 'queue-1', name: 'Billing answers', itemId: 'item-1' } },
    }),
]

const IDS = ITEMS.map((item) => item.id)

const LOADED_CELLS: TracesTableCells = {
    previews: new Map([
        ['trace-1', ready(makeTracePreview('trace-1'))],
        [
            'trace-2',
            ready(
                makeTracePreview('trace-2', {
                    input: 'Summarize the attached contract and list every clause that mentions termination, renewal or notice periods, with the page each one is on.',
                    output: null,
                    outputMissingReason: 'timed_out',
                })
            ),
        ],
        ['trace-3', ready(makeTracePreview('trace-3', { input: null, inputMissingReason: 'too_large', output: null }))],
    ]),
    people: new Map<string, TraceCellLoad<TracePersonApi | null>>([
        ['trace-1', ready({ distinctId: 'ana@example.com', label: 'Ana Example' })],
        ['trace-2', ready({ distinctId: 'f3c9a1d2', label: 'f3c9a1d2' })],
        ['trace-3', ready(null)],
    ]),
    sentiments: new Map<string, TraceCellLoad<TraceSentimentApi | null>>([
        ['trace-1', ready({ label: 'positive', score: 0.82 })],
        ['trace-2', ready({ label: 'negative', score: 0.71 })],
        ['trace-3', ready(null)],
    ]),
}

function SampleTable({ items, cells }: { items: TraceListItemApi[]; cells: TracesTableCells }): JSX.Element {
    return (
        <LemonTable<TraceListItemApi>
            columns={tracesTableColumns({ linkTo: (item) => `/ai-observability/traces/${item.id}`, cells })}
            dataSource={items}
            rowKey={(item) => item.id}
        />
    )
}

const meta: Meta<typeof SampleTable> = {
    title: 'Scenes-App/AI observability/Traces/Traces table columns',
    component: SampleTable,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { items: ITEMS, cells: LOADED_CELLS },
}
export default meta

type Story = StoryObj<typeof SampleTable>

export const Rows: Story = {}

export const SlowCellsLoading: Story = { args: { cells: makeUnreadTraceCells(IDS, 'loading') } }

export const SlowCellsFailed: Story = { args: { cells: makeUnreadTraceCells(IDS, 'error') } }

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-120">
                <StoryComponent />
            </div>
        ),
    ],
}

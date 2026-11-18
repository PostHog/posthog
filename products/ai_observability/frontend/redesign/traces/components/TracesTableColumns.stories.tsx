import type { Meta, StoryObj } from '@storybook/react'

import { LemonTable } from 'lib/lemon-ui/LemonTable'

import type { TraceListItemApi } from '../../../generated/api.schemas'
import { makeTraceListItem } from '../testFixtures'
import { tracesTableColumns } from './TracesTableColumns'

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
        toolsCalled: ['search_docs', 'read_file', 'run_sql', 'send_email'],
        review: { review: null, queue: { id: 'queue-1', name: 'Billing answers', itemId: 'item-1' } },
    }),
]

function SampleTable({ items }: { items: TraceListItemApi[] }): JSX.Element {
    return (
        <LemonTable<TraceListItemApi>
            columns={tracesTableColumns({ linkTo: (item) => `/ai-observability/traces/${item.id}` })}
            dataSource={items}
            rowKey={(item) => item.id}
        />
    )
}

const meta: Meta<typeof SampleTable> = {
    title: 'Scenes-App/AI observability/Traces/Traces table columns',
    component: SampleTable,
    parameters: { testOptions: { snapshotBrowsers: [] } },
    args: { items: ITEMS },
}
export default meta

type Story = StoryObj<typeof SampleTable>

export const Rows: Story = {}

export const NarrowContainer: Story = {
    decorators: [
        (StoryComponent) => (
            <div className="w-120">
                <StoryComponent />
            </div>
        ),
    ],
}

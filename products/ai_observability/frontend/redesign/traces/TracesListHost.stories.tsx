import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { urls } from 'scenes/urls'

import { mswDecorator } from '~/mocks/browser'

import type { TraceListApi } from '../../generated/api.schemas'
import { makeTraceListItem } from './testFixtures'
import { TracesListHost } from './TracesListHost'

const PAGE: TraceListApi = {
    items: [
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
        }),
        makeTraceListItem({
            id: 'trace-3',
            name: null,
            createdAt: '2026-09-01T11:38:00Z',
            isSupportTrace: true,
            review: { review: null, queue: { id: 'queue-1', name: 'Billing answers', itemId: 'item-1' } },
        }),
    ],
    counts: { total: 3, errors: 1, feedback: 0 },
    nextCursor: 'cursor-2',
}

const meta: Meta<typeof TracesListHost> = {
    title: 'Scenes-App/AI observability/Traces/Traces list',
    component: TracesListHost,
    decorators: [mswDecorator({ get: { '/api/projects/:team_id/ai_observability/traces/': PAGE } })],
    parameters: {
        mockDate: '2026-09-01',
        pageUrl: urls.aiObservabilityTraces(),
        featureFlags: [FEATURE_FLAGS.LLM_OBSERVABILITY_TRACE_SEARCH],
        testOptions: { snapshotBrowsers: [], waitForSelector: 'text=rag-query' },
    },
}
export default meta

type Story = StoryObj<typeof TracesListHost>

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

import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { cleanup, fireEvent, render } from '@testing-library/react'
import { router } from 'kea-router'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { traceDrawerLogic } from '../redesign/trace/traceDrawerLogic'
import { AIObservabilityReviewQueues } from './AIObservabilityReviewQueues'
import { reviewQueuesApi } from './reviewQueuesApi'

jest.mock('./reviewQueuesApi', () => ({
    reviewQueuesApi: {
        listQueues: jest.fn(),
        getQueue: jest.fn(),
        listQueueItems: jest.fn(),
    },
}))

const mockReviewQueuesApi = reviewQueuesApi as jest.Mocked<typeof reviewQueuesApi>

const CREATED_BY = {
    id: 1,
    uuid: 'user-1',
    distinct_id: 'user-1',
    first_name: 'Test',
    last_name: 'User',
    email: 'test@example.com',
    hedgehog_config: null,
}
const QUEUE = {
    id: 'queue_1',
    name: 'Support',
    pending_item_count: 2,
    created_at: '2026-03-13T12:00:00Z',
    updated_at: '2026-03-13T12:00:00Z',
    created_by: CREATED_BY,
    team: MOCK_DEFAULT_TEAM.id,
}
const items = ['trace_1', 'trace_2'].map((traceId, index) => ({
    id: `item_${index}`,
    queue_id: 'queue_1',
    queue_name: 'Support',
    trace_id: traceId,
    created_at: '2026-03-13T12:00:00Z',
    updated_at: '2026-03-13T12:00:00Z',
    created_by: CREATED_BY,
    team: MOCK_DEFAULT_TEAM.id,
}))

describe('AIObservabilityReviewQueues', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockReviewQueuesApi.listQueues.mockResolvedValue({ count: 1, next: null, previous: null, results: [QUEUE] })
        mockReviewQueuesApi.getQueue.mockResolvedValue(QUEUE)
        mockReviewQueuesApi.listQueueItems.mockResolvedValue({ count: 2, next: null, previous: null, results: items })
        localStorage.clear()
        featureFlagLogic.mount()
        router.actions.push(urls.aiObservabilityReviews(), { queue_id: 'queue_1' })
    })

    afterEach(() => {
        cleanup()
    })

    it('opens a queued trace in the drawer from its link, with the queue rows to step through', async () => {
        const { findByText } = render(<AIObservabilityReviewQueues />)

        fireEvent.click(await findByText('trace_1'))

        expect(router.values.location.pathname).toContain(urls.aiObservabilityReviews())
        expect(router.values.searchParams).toEqual({ queue_id: 'queue_1', trace: 'trace_1' })
        expect(traceDrawerLogic({ listId: 'review-queue' }).values.rows).toEqual([
            { traceId: 'trace_1', timestamp: null, stepId: null },
            { traceId: 'trace_2', timestamp: null, stepId: null },
        ])
    })
})

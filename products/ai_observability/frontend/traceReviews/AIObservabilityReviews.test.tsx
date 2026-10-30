import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { AIObservabilityReviews } from './AIObservabilityReviews'
import { TRACE_REVIEWS_PER_PAGE } from './aiObservabilityReviewsLogic'
import { traceReviewsApi } from './traceReviewsApi'
import type { TraceReview } from './types'

jest.mock('./traceReviewsApi', () => ({
    ...jest.requireActual('./traceReviewsApi'),
    traceReviewsApi: {
        list: jest.fn(),
    },
}))
jest.mock('../generated/api', () => ({
    ...jest.requireActual('../generated/api'),
    llmAnalyticsScoreDefinitionsList: jest
        .fn()
        .mockResolvedValue({ results: [], count: 0, next: null, previous: null }),
}))

const mockTraceReviewsList = traceReviewsApi.list as jest.MockedFunction<typeof traceReviewsApi.list>

const reviews: TraceReview[] = Array.from({ length: TRACE_REVIEWS_PER_PAGE }, (_, i) => ({
    id: `review-${i}`,
    trace_id: `trace-${i}`,
    trace_url: '',
    comment: null,
    created_at: '2026-03-12T00:00:00Z',
    updated_at: '2026-03-12T01:00:00Z',
    created_by: null,
    reviewed_by: null,
    scores: [],
    team: 1,
}))

describe('AIObservabilityReviews', () => {
    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        mockTraceReviewsList.mockResolvedValue({ results: reviews, count: TRACE_REVIEWS_PER_PAGE * 2 })
        router.actions.push(urls.aiObservabilityReviews())
    })

    afterEach(() => {
        cleanup()
    })

    it('loads the next page when the next page button is clicked', async () => {
        const { findAllByText, getByLabelText } = render(<AIObservabilityReviews />)
        await findAllByText(`1-${TRACE_REVIEWS_PER_PAGE} of ${TRACE_REVIEWS_PER_PAGE * 2} reviews`)

        fireEvent.click(getByLabelText('Next page'))

        // Generous timeout: the logic debounces reloads by 300ms once results are loaded.
        await waitFor(
            () =>
                expect(mockTraceReviewsList).toHaveBeenLastCalledWith(
                    expect.objectContaining({ offset: TRACE_REVIEWS_PER_PAGE })
                ),
            { timeout: 3000 }
        )
        expect(router.values.searchParams.review_page).toBe(2)
    })

    it('keeps the new sort order when a column header is clicked', async () => {
        const { findAllByText, getByText } = render(<AIObservabilityReviews />)
        await findAllByText(`1-${TRACE_REVIEWS_PER_PAGE} of ${TRACE_REVIEWS_PER_PAGE * 2} reviews`)

        fireEvent.click(getByText('Updated'))

        await waitFor(
            () =>
                expect(mockTraceReviewsList).toHaveBeenLastCalledWith(
                    expect.objectContaining({ order_by: 'updated_at' })
                ),
            { timeout: 3000 }
        )
        expect(router.values.searchParams.review_order_by).toBe('updated_at')
    })
})

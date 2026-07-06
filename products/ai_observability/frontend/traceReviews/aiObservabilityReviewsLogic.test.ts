import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'
import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { aiObservabilityReviewsLogic } from './aiObservabilityReviewsLogic'
import { traceReviewsApi } from './traceReviewsApi'
import { CLIPBOARD_ROW_LIMIT } from './traceReviewsExport'
import type { TraceReview } from './types'

jest.mock('lib/utils/copyToClipboard')
jest.mock('@posthog/lemon-ui', () => ({
    ...jest.requireActual('@posthog/lemon-ui'),
    lemonToast: {
        error: jest.fn(),
        warning: jest.fn(),
    },
}))
jest.mock('./traceReviewsApi', () => ({
    ...jest.requireActual('./traceReviewsApi'),
    traceReviewsApi: {
        list: jest.fn(),
    },
}))
jest.mock('../generated/api', () => ({
    aiObservabilityScoreDefinitionsList: jest
        .fn()
        .mockResolvedValue({ results: [], count: 0, next: null, previous: null }),
}))

const mockTraceReviewsList = traceReviewsApi.list as jest.MockedFunction<typeof traceReviewsApi.list>
const mockCopyToClipboard = copyToClipboard as jest.MockedFunction<typeof copyToClipboard>
const mockLemonToastError = lemonToast.error as jest.MockedFunction<typeof lemonToast.error>
const mockLemonToastWarning = lemonToast.warning as jest.MockedFunction<typeof lemonToast.warning>

const baseReview: TraceReview = {
    id: 'review-1',
    trace_id: 'trace-abc',
    trace_url: 'https://us.posthog.com/project/1/ai-observability/traces/trace-abc',
    comment: 'Looks good',
    created_at: '2026-03-12T00:00:00Z',
    updated_at: '2026-03-12T01:00:00Z',
    created_by: null,
    reviewed_by: null,
    scores: [],
    team: 1,
}

describe('aiObservabilityReviewsLogic.copyReviewsToClipboard', () => {
    let logic: ReturnType<typeof aiObservabilityReviewsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.clearAllMocks()
        logic = aiObservabilityReviewsLogic()
        // Stub the initial mount load so afterMount doesn't interfere with our test mocks.
        mockTraceReviewsList.mockResolvedValue({ results: [], count: 0 })
        logic.mount()
    })

    it('copies the formatted payload to the clipboard on the happy path', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockResolvedValueOnce({ results: [baseReview], count: 1 })

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockCopyToClipboard).toHaveBeenCalledTimes(1)
        expect(mockCopyToClipboard.mock.calls[0][1]).toBe('reviews')
    })

    it('shows an error toast and skips the clipboard write when there are no reviews', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockResolvedValueOnce({ results: [], count: 0 })

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockLemonToastError).toHaveBeenCalledWith('No reviews to copy!')
        expect(mockCopyToClipboard).not.toHaveBeenCalled()
    })

    it('shows a warning pointing at the file export when the dataset exceeds the cap', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockResolvedValueOnce({
            results: [baseReview],
            count: CLIPBOARD_ROW_LIMIT + 1,
        })

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockLemonToastWarning).toHaveBeenCalledTimes(1)
        const message = mockLemonToastWarning.mock.calls[0][0] as string
        expect(message).toContain(String(CLIPBOARD_ROW_LIMIT + 1))
        expect(message).toContain('Export current columns')
        expect(mockCopyToClipboard).not.toHaveBeenCalled()
    })

    it('falls back to an error toast when the fetch fails', async () => {
        mockTraceReviewsList.mockReset()
        mockTraceReviewsList.mockRejectedValueOnce(new Error('network down'))

        await expectLogic(logic, () => {
            logic.actions.copyReviewsToClipboard('csv')
        }).toFinishAllListeners()

        expect(mockLemonToastError).toHaveBeenCalledWith('Copy failed!')
    })

    it('ignores bare aliases on the shared URL — they belong to the Scorers sub-tab', () => {
        // The Scorers sub-tab writes a bare `search` to this shared URL; it rides
        // along when we pass URL params through but must never seed the review filters.
        router.actions.push(urls.aiObservabilityReviews(), {
            search: 'from-scorers',
            human_reviews_tab: 'reviews',
        })
        expect(logic.values.filters.search).toBe('')

        logic.actions.setFilters({ search: 'my-review-query' }, true, false)

        expect(logic.values.filters.search).toBe('my-review-query')
        // We preserved the bare alias on the URL rather than stripping it...
        expect(router.values.searchParams.search).toBe('from-scorers')
        // ...and the edit lives in the namespaced param.
        expect(router.values.searchParams.review_search).toBe('my-review-query')
    })

    it('keeps a review filter cleared instead of resurrecting a stale bare alias', () => {
        router.actions.push(urls.aiObservabilityReviews(), {
            search: 'from-scorers',
            human_reviews_tab: 'reviews',
        })
        logic.actions.setFilters({ search: 'my-review-query' }, true, false)
        expect(logic.values.filters.search).toBe('my-review-query')

        // Clearing back to the default drops review_search from the URL; the
        // lingering bare `search` must not leak back in on the urlToAction pass.
        logic.actions.setFilters({ search: '' }, true, false)

        expect(logic.values.filters.search).toBe('')
        expect(router.values.searchParams.review_search).toBeUndefined()
        expect(router.values.searchParams.search).toBe('from-scorers')
    })

    it('cancels an earlier invocation when called twice in quick succession', async () => {
        mockTraceReviewsList.mockReset()
        let resolveFirst: ((value: { results: TraceReview[]; count: number }) => void) | undefined
        mockTraceReviewsList
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        resolveFirst = resolve
                    })
            )
            .mockResolvedValueOnce({ results: [baseReview], count: 1 })

        // Click 1 hangs on the API; click 2 resolves immediately and should win.
        logic.actions.copyReviewsToClipboard('csv')
        logic.actions.copyReviewsToClipboard('csv')

        const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))
        await flush()
        await flush()

        // Click 2 has finished and written to the clipboard.
        expect(mockCopyToClipboard).toHaveBeenCalledTimes(1)

        // Now unblock click 1: when it resumes, breakpoint() should detect the newer
        // invocation and throw, so no second clipboard write happens.
        resolveFirst?.({ results: [baseReview], count: 1 })
        await flush()
        await flush()

        expect(mockCopyToClipboard).toHaveBeenCalledTimes(1)
    })
})

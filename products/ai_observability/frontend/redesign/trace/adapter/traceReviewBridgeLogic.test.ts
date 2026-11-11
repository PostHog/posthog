import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { traceReviewsLazyLoaderLogic } from '../../../traceReviews/traceReviewsLazyLoaderLogic'
import type { TraceReview } from '../../../traceReviews/types'
import { traceReviewLogic } from '../traceReviewLogic'
import { traceReviewBridgeLogic } from './traceReviewBridgeLogic'

const REVIEW_URL = '/api/projects/:team_id/ai_observability/traces/:id/review/'

function savedReview(traceId: string): TraceReview {
    return {
        id: 'r1',
        trace_id: traceId,
        trace_url: '',
        comment: null,
        created_at: '2026-09-01T10:00:00Z',
        updated_at: null,
        created_by: null,
        reviewed_by: null,
        scores: [],
        team: 1,
    }
}

describe('traceReviewBridgeLogic', () => {
    beforeEach(() => {
        useMocks({ get: { [REVIEW_URL]: () => [200, { review: null, queue: null }] } })
        initKeaTests()
    })

    it.each([
        [
            'a saved review',
            (traceId: string) => traceReviewsLazyLoaderLogic.actions.setTraceReview(savedReview(traceId)),
        ],
        ['a removed review', (traceId: string) => traceReviewsLazyLoaderLogic.actions.setTraceAsUnreviewed(traceId)],
    ])('reloads the status after %s for its own trace only', async (_name, change) => {
        const review = traceReviewLogic({ traceId: 'trace-1' })
        review.mount()
        traceReviewBridgeLogic({ traceId: 'trace-1' }).mount()
        await expectLogic(review).toDispatchActions(['loadReviewStatusSuccess'])

        await expectLogic(review, () => change('trace-2')).toNotHaveDispatchedActions(['loadReviewStatus'])
        await expectLogic(review, () => change('trace-1')).toDispatchActions(['loadReviewStatus'])
    })
})

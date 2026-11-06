import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceReviewStatusApi } from '../../generated/api.schemas'
import { decodeIdSegment } from './adapter/testFixtures'
import { traceReviewLogic } from './traceReviewLogic'

const REVIEW_URL = '/api/projects/:team_id/ai_observability/traces/:id/review/'
const QUEUE_ITEM_URL = '/api/projects/:team_id/llm_analytics/review_queue_items/:id/'

const QUEUED: TraceReviewStatusApi = {
    review: null,
    queue: { id: 'q1', name: 'Support QA', itemId: 'i1' },
}
const NOTHING: TraceReviewStatusApi = { review: null, queue: null }

describe('traceReviewLogic', () => {
    let statuses: Record<string, TraceReviewStatusApi>
    let reviewStatus: number
    let deletedItems: string[]
    let deleteStatus: number

    beforeEach(() => {
        statuses = { 'trace-1': QUEUED, 'trace-2': NOTHING }
        reviewStatus = 200
        deletedItems = []
        deleteStatus = 204
        useMocks({
            get: {
                [REVIEW_URL]: ({ params }) =>
                    reviewStatus === 200
                        ? [200, statuses[decodeIdSegment(String(params.id))]]
                        : [reviewStatus, { detail: 'nope' }],
            },
            delete: {
                [QUEUE_ITEM_URL]: ({ params }) => {
                    deletedItems.push(String(params.id))
                    if (deleteStatus !== 204) {
                        return [deleteStatus, { detail: 'nope' }]
                    }
                    statuses['trace-1'] = NOTHING
                    return [204]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
    })

    it('loads the status of its own trace and links its queue', async () => {
        const first = traceReviewLogic({ traceId: 'trace-1' })
        const second = traceReviewLogic({ traceId: 'trace-2' })
        first.mount()
        second.mount()

        await expectLogic(first).toDispatchActions(['loadReviewStatusSuccess'])
        await expectLogic(second).toDispatchActions(['loadReviewStatusSuccess'])

        expect(first.values.reviewStatus).toEqual(QUEUED)
        expect(first.values.queueHref).toMatch(/\/ai-observability\/reviews\?queue_id=q1$/)
        expect(second.values.reviewStatus).toEqual(NOTHING)
        expect(second.values.queueHref).toBeNull()
    })

    it.each([
        { name: 'succeeds', status: 204, queueAfterRemove: null },
        { name: 'fails', status: 404, queueAfterRemove: QUEUED.queue },
    ])('removes the trace from its queue and reloads when the delete $name', async ({ status, queueAfterRemove }) => {
        silenceKeaLoadersErrors()
        deleteStatus = status
        const logic = traceReviewLogic({ traceId: 'trace-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReviewStatusSuccess'])

        logic.actions.removeFromQueue()

        await expectLogic(logic).toDispatchActions([
            status === 204 ? 'removeFromQueueSuccess' : 'removeFromQueueFailure',
            'loadReviewStatusSuccess',
        ])
        expect(deletedItems).toEqual(['i1'])
        expect(logic.values.reviewStatus?.queue ?? null).toEqual(queueAfterRemove)
        expect(logic.values.removeFromQueueLoading).toBe(false)
    })

    it('flags a failed read and keeps the last status when a reload fails', async () => {
        silenceKeaLoadersErrors()
        const logic = traceReviewLogic({ traceId: 'trace-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadReviewStatusSuccess'])
        expect(logic.values.reviewStatusFailed).toBe(false)

        reviewStatus = 500
        logic.actions.loadReviewStatus()

        await expectLogic(logic).toDispatchActions(['loadReviewStatusFailure'])
        expect(logic.values.reviewStatus).toEqual(QUEUED)
        expect(logic.values.reviewStatusFailed).toBe(true)
    })
})

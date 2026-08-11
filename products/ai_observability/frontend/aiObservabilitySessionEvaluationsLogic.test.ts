import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiObservabilitySessionEvaluationsLogic } from './aiObservabilitySessionEvaluationsLogic'

// uuid, timestamp, evaluation_id, evaluation_name, generation_id, trace_id, result, reasoning,
// applicable, evaluation_type, result_type, sentiment_label, sentiment_score, session_id, skipped
const SESSION_VERDICT_ROW = [
    'run-1',
    '2026-07-29T00:00:00Z',
    'eval-1',
    'Goal reached',
    '',
    '',
    true,
    'The user got their answer',
    true,
    'hog',
    'boolean',
    null,
    null,
    'ai-session-9',
    false,
]

describe('aiObservabilitySessionEvaluationsLogic', () => {
    let logic: ReturnType<typeof aiObservabilitySessionEvaluationsLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [200, { results: [SESSION_VERDICT_ROW] }],
            },
        })
        initKeaTests()
        logic = aiObservabilitySessionEvaluationsLogic({ sessionId: 'ai-session-9' })
        logic.mount()
    })

    // Session verdicts are the only ones with no $ai_trace_id, so this logic exists purely to read
    // them by $ai_session_id through the shared query. Result mapping is mapEvaluationRunRow's job
    // and is covered in utils.test.ts; deduping is getEvalSummaries' and is covered in
    // EvalResultBadges.test.tsx. What is only testable here is the wiring.
    it('reads session verdicts as ordinary evaluation runs', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(logic.values.sessionEvaluations).toHaveLength(1)
        expect(logic.values.sessionEvaluations[0]).toMatchObject({
            evaluation_id: 'eval-1',
            evaluation_name: 'Goal reached',
            session_id: 'ai-session-9',
            result: true,
        })
    })

    it('does not query when there is no session id', async () => {
        const querySpy = jest.spyOn(api, 'queryHogQL')
        try {
            const empty = aiObservabilitySessionEvaluationsLogic({ sessionId: '' })
            empty.mount()
            querySpy.mockClear()

            await expectLogic(empty, () => {
                empty.actions.loadSessionEvaluations()
            }).toFinishAllListeners()

            expect(querySpy).not.toHaveBeenCalled()
            expect(empty.values.sessionEvaluations).toEqual([])
        } finally {
            querySpy.mockRestore()
        }
    })

    it('clears verdicts when the query fails', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [500, { error: 'nope' }],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(logic.values.sessionEvaluations).toEqual([])
        expect(logic.values.sessionEvaluationsLoading).toBe(false)
    })
})

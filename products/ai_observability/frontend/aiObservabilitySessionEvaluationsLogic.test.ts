import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { aiObservabilitySessionEvaluationsLogic } from './aiObservabilitySessionEvaluationsLogic'

describe('aiObservabilitySessionEvaluationsLogic', () => {
    let logic: ReturnType<typeof aiObservabilitySessionEvaluationsLogic.build>

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    200,
                    {
                        results: [
                            [
                                'eval-1',
                                'Goal reached',
                                true,
                                'The user got their answer',
                                false,
                                '2026-07-29T00:00:00Z',
                            ],
                        ],
                    },
                ],
            },
        })
        initKeaTests()
        logic = aiObservabilitySessionEvaluationsLogic({ sessionId: 'ai-session-9' })
        logic.mount()
    })

    it('loads session-scoped verdicts', async () => {
        await expectLogic(logic, () => {
            logic.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(logic.values.sessionEvaluations).toEqual([
            {
                evaluationId: 'eval-1',
                evaluationName: 'Goal reached',
                verdict: true,
                skipped: false,
                reasoning: 'The user got their answer',
                timestamp: '2026-07-29T00:00:00Z',
            },
        ])
    })

    // HogQL types $ai_evaluation_result from each team's own property definition: teams that
    // haven't registered it as Boolean get the JSON bool back as a string, not a JS boolean.
    // `Boolean('false') === true`, so a naive cast previously rendered a failing session
    // evaluation as passing.
    it.each([
        [true, true],
        [false, false],
        ['true', true],
        ['True', true],
        ['1', true],
        ['false', false],
        ['0', false],
    ])('maps raw verdict %p to %p', async (rawVerdict, expectedVerdict) => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    200,
                    {
                        results: [['eval-1', 'Goal reached', rawVerdict, 'reasoning', false, '2026-07-29T00:00:00Z']],
                    },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(logic.values.sessionEvaluations[0].verdict).toBe(expectedVerdict)
    })

    it('treats a null verdict as not-yet-decided rather than a failure', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    200,
                    {
                        results: [
                            [
                                'eval-2',
                                'Stayed on topic',
                                null,
                                'Not applicable to this session',
                                false,
                                '2026-07-29T01:00:00Z',
                            ],
                        ],
                    },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(logic.values.sessionEvaluations[0].verdict).toBeNull()
    })

    // A skip carries `result: false` when the evaluation disallows N/A, so dropping the skipped
    // column renders a session that was never graded as one that failed.
    it('keeps a skipped run distinguishable from a failing one', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    200,
                    {
                        results: [
                            [
                                'eval-3',
                                'Goal reached',
                                false,
                                'Session exceeds 2500 events',
                                true,
                                '2026-07-29T02:00:00Z',
                            ],
                        ],
                    },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(logic.values.sessionEvaluations[0].skipped).toBe(true)
        expect(logic.values.sessionEvaluations[0].verdict).toBe(false)
    })

    // A session that resumes after being evaluated can be graded again; showing both verdicts puts
    // a stale tag next to a fresh one with nothing to tell them apart.
    it('keeps only the newest verdict per evaluation', async () => {
        useMocks({
            post: {
                '/api/environments/:team_id/query/:kind': () => [
                    200,
                    {
                        results: [
                            ['eval-1', 'Goal reached', true, 'newer', false, '2026-07-29T03:00:00Z'],
                            ['eval-1', 'Goal reached', false, 'older', false, '2026-07-29T01:00:00Z'],
                        ],
                    },
                ],
            },
        })

        await expectLogic(logic, () => {
            logic.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(logic.values.sessionEvaluations).toHaveLength(1)
        expect(logic.values.sessionEvaluations[0].reasoning).toBe('newer')
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
})

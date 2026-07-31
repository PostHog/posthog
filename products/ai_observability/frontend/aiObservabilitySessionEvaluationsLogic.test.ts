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
                            ['eval-1', 'Goal reached', true, 'The user got their answer', '2026-07-29T00:00:00Z'],
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
                        results: [['eval-1', 'Goal reached', rawVerdict, 'reasoning', '2026-07-29T00:00:00Z']],
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

    it('does not query when there is no session id', async () => {
        const querySpy = jest.spyOn(api, 'query')
        const empty = aiObservabilitySessionEvaluationsLogic({ sessionId: '' })
        empty.mount()
        querySpy.mockClear()

        await expectLogic(empty, () => {
            empty.actions.loadSessionEvaluations()
        }).toFinishAllListeners()

        expect(querySpy).not.toHaveBeenCalled()
        expect(empty.values.sessionEvaluations).toEqual([])
    })
})

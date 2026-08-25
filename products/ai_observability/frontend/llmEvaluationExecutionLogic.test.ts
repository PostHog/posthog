import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationExecutionLogic } from './llmEvaluationExecutionLogic'

describe('llmEvaluationExecutionLogic', () => {
    let logic: ReturnType<typeof llmEvaluationExecutionLogic.build>
    let runResponse: [number, Record<string, unknown>] | Response

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/evaluation_runs/': () => runResponse,
            },
        })
        initKeaTests()
        logic = llmEvaluationExecutionLogic()
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    // The endpoint answers in DRF's shape, so the handler in `initKea` renders the reason. Toasting
    // here as well would show the user the same sentence twice.
    it('leaves a refused run to the shared handler', async () => {
        runResponse = [
            400,
            {
                type: 'validation_error',
                code: 'evaluation_target_mismatch',
                detail: "This evaluation runs on the whole trace, so it can't be re-run against a single generation.",
                attr: null,
            },
        ]
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        await expectLogic(logic, () => {
            logic.actions.runEvaluation('eval-1', 'event-1', '2026-08-06T00:00:00Z', '$ai_generation')
        }).toDispatchActions(['runEvaluationFailure'])

        expect(toast.mock.calls).toEqual([
            [
                "Run evaluation failed: This evaluation runs on the whole trace, so it can't be re-run against a single generation.",
            ],
        ])
    })

    // `initKea` only toasts a failure that carries a status, so a request that never reached the
    // backend would otherwise leave the user with no answer at all.
    it('reports a failure that never got a status', async () => {
        runResponse = new Response('<!doctype html>', {
            status: 200,
            headers: { 'content-type': 'application/json' },
        })
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        await expectLogic(logic, () => {
            logic.actions.runEvaluation('eval-1', 'event-1', '2026-08-06T00:00:00Z', '$ai_generation')
        }).toDispatchActions(['runEvaluationFailure'])

        expect(toast.mock.calls).toEqual([['Failed to start evaluation']])
    })
})

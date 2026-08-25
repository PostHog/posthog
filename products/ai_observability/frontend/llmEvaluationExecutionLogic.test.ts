import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationExecutionLogic } from './llmEvaluationExecutionLogic'

// A fault must keep failing the loader so it still reaches error tracking. The status-less case
// is the sharp one: `api.ts` throws it for a 2xx whose body could not be read, where the run may
// already have started, so swallowing it would lose a started run and report nothing.
const RUN_FAULTS: [string, () => [number, Record<string, unknown>] | Response][] = [
    ['a server error', () => [500, { error: 'Failed to start evaluation' }]],
    [
        'a response with no readable body',
        () => new Response('<!doctype html>', { status: 200, headers: { 'content-type': 'application/json' } }),
    ],
]

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

    // The backend turns down a trace- or session-target evaluation with a sentence saying why.
    // Discarding it left the user with "Failed to start evaluation" and nothing to act on.
    it('shows the reason the backend gave and does not report the rejection as a failure', async () => {
        runResponse = [
            400,
            { error: "This evaluation runs on the whole trace, so it can't be re-run against a single generation." },
        ]
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        await expectLogic(logic, () => {
            logic.actions.runEvaluation('eval-1', 'event-1', '2026-08-06T00:00:00Z', '$ai_generation')
        })
            .toDispatchActions(['runEvaluationSuccess'])
            .toNotHaveDispatchedActions(['runEvaluationFailure'])

        expect(toast).toHaveBeenCalledWith(
            "This evaluation runs on the whole trace, so it can't be re-run against a single generation."
        )
        expect(logic.values.lastRunWorkflowId).toBeNull()
    })

    it.each(RUN_FAULTS)('keeps failing the loader on %s', async (_, buildResponse) => {
        runResponse = buildResponse()
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        await expectLogic(logic, () => {
            logic.actions.runEvaluation('eval-1', 'event-1', '2026-08-06T00:00:00Z', '$ai_generation')
        }).toDispatchActions(['runEvaluationFailure'])

        expect(toast).toHaveBeenCalledWith('Failed to start evaluation')
    })
})

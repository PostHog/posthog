import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationExecutionLogic } from './llmEvaluationExecutionLogic'

describe('llmEvaluationExecutionLogic', () => {
    let logic: ReturnType<typeof llmEvaluationExecutionLogic.build>
    let runResponse: [number, Record<string, unknown>]

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

    // A server fault is a defect, so it must keep failing the loader and reaching error tracking.
    it('keeps failing the loader on a server error', async () => {
        runResponse = [500, { error: 'Failed to start evaluation' }]
        jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        await expectLogic(logic, () => {
            logic.actions.runEvaluation('eval-1', 'event-1', '2026-08-06T00:00:00Z', '$ai_generation')
        }).toDispatchActions(['runEvaluationFailure'])
    })
})

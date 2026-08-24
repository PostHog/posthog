import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationExecutionLogic } from './llmEvaluationExecutionLogic'

jest.mock('lib/lemon-ui/LemonToast')

const TRACE_TARGET_REJECTION =
    "This evaluation runs on the whole trace, so it can't be re-run against a single generation. It runs " +
    'automatically once the trace finishes.'

describe('llmEvaluationExecutionLogic', () => {
    let logic: ReturnType<typeof llmEvaluationExecutionLogic.build>
    let response: [number, Record<string, unknown>]

    beforeEach(() => {
        useMocks({
            post: {
                '/api/environments/:team_id/evaluation_runs/': () => response,
            },
        })
        initKeaTests()
        logic = llmEvaluationExecutionLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.clearAllMocks()
    })

    function runEvaluation(): void {
        logic.actions.runEvaluation('eval-1', 'generation-1', '2026-08-06T00:00:00Z', '$ai_generation')
    }

    // The endpoint only knows how to run one generation, so it turns down a trace- or session-target
    // evaluation with a 400 that explains why. Discarding that sentence for a generic toast left the
    // user with nothing to act on.
    it('shows the reason the backend gave for turning the run down', async () => {
        response = [400, { error: TRACE_TARGET_REJECTION }]

        await expectLogic(logic, runEvaluation).toDispatchActions(['runEvaluationSuccess'])

        expect(lemonToast.error).toHaveBeenCalledWith(TRACE_TARGET_REJECTION)
        expect(logic.values.evaluationRun).toBeNull()
    })

    // Rethrowing a rejection files it as an unhandled exception, which buries real faults under
    // behavior that is working as designed. A 500 is a real fault, so it must keep failing the loader.
    it('fails the loader on a server error so it still reaches error tracking', async () => {
        response = [500, { error: 'Failed to start evaluation' }]

        await expectLogic(logic, runEvaluation).toDispatchActions(['runEvaluationFailure'])
    })
})

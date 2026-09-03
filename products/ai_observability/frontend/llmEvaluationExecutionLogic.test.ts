import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { llmEvaluationExecutionLogic } from './llmEvaluationExecutionLogic'

// A guard keyed on the status alone lets all three pass silently, because the shared handler has
// no `detail` or `statusText` to render for them.
const NOTHING_FOR_THE_SHARED_HANDLER: [string, () => Response][] = [
    [
        'a proxy answering in HTML',
        () => new Response('<html>Bad Request</html>', { status: 400, headers: { 'content-type': 'text/html' } }),
    ],
    ['a gateway answering with an empty body', () => new Response(null, { status: 502 })],
    [
        'a body that could not be read',
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

    // A local toast here as well would show the user the same sentence twice.
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

    it.each(NOTHING_FOR_THE_SHARED_HANDLER)('answers %s', async (_label, buildResponse) => {
        runResponse = buildResponse()
        const toast = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

        await expectLogic(logic, () => {
            logic.actions.runEvaluation('eval-1', 'event-1', '2026-08-06T00:00:00Z', '$ai_generation')
        }).toDispatchActions(['runEvaluationFailure'])

        expect(toast.mock.calls).toEqual([['Failed to start evaluation']])
    })
})

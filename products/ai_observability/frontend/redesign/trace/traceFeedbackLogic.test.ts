import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeFeedback, makeTraceResource } from './adapter/testFixtures'
import { traceFeedbackLogic } from './traceFeedbackLogic'
import { traceViewLogic } from './traceViewLogic'

const TRACE_URL = '/api/projects/:team_id/ai_observability/traces/:id/'
const EVALUATIONS_URL = '/api/projects/:team_id/ai_observability/traces/:id/evaluations/'
const FEEDBACK_URL = '/api/projects/:team_id/ai_observability/traces/:id/feedback/'

describe('traceFeedbackLogic', () => {
    let feedbackHints: (string | null)[] = []
    let traceGate: Promise<void> = Promise.resolve()
    let feedbackStatus = 200

    beforeEach(() => {
        feedbackHints = []
        traceGate = Promise.resolve()
        feedbackStatus = 200
        useMocks({
            get: {
                [TRACE_URL]: async () => {
                    await traceGate
                    return [200, makeTraceResource({ createdAt: '2026-09-01T10:15:00Z' })]
                },
                [EVALUATIONS_URL]: () => [200, { results: [] }],
                [FEEDBACK_URL]: ({ request }) => {
                    feedbackHints.push(new URL(request.url).searchParams.get('timestamp_hint'))
                    return feedbackStatus === 200 ? [200, makeFeedback()] : [feedbackStatus, { detail: 'nope' }]
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
    })

    function mount(timestampHint: string | null): ReturnType<typeof traceFeedbackLogic.build> {
        traceViewLogic({ traceId: 'trace-1', timestampHint }).mount()
        const logic = traceFeedbackLogic({ traceId: 'trace-1', timestampHint })
        logic.mount()
        return logic
    }

    it('loads on mount with the link timestamp, before the trace arrives', async () => {
        traceGate = new Promise(() => {})
        const logic = mount('2026-08-31T00:00:00Z')

        await expectLogic(logic).toDispatchActions(['loadTraceFeedbackSuccess'])

        expect(feedbackHints).toEqual(['2026-08-31T00:00:00Z'])
        expect(logic.values.traceFeedback).toEqual(makeFeedback())
    })

    it('without a link timestamp, loads once the trace arrives with its timestamp', async () => {
        let releaseTrace = (): void => {}
        traceGate = new Promise((resolve) => {
            releaseTrace = resolve
        })
        const logic = mount(null)
        expect(logic.values.traceFeedbackLoading).toBe(false)

        releaseTrace()

        await expectLogic(logic).toDispatchActions(['loadTraceFeedbackSuccess'])
        expect(feedbackHints).toEqual(['2026-09-01T10:15:00Z'])
    })

    test.each([
        ['the link timestamp', '2026-08-31T00:00:00Z', '2026-08-31T00:00:00Z'],
        ["the trace's timestamp", null, '2026-09-01T10:15:00Z'],
    ])('marks a failed read, keeps no feedback, and retries with %s', async (_name, timestampHint, expectedHint) => {
        silenceKeaLoadersErrors()
        feedbackStatus = 500
        const logic = mount(timestampHint)

        await expectLogic(logic)
            .toDispatchActions(['loadTraceFeedbackFailure'])
            .toMatchValues({ traceFeedback: null, traceFeedbackFailed: true })

        feedbackStatus = 200
        await expectLogic(logic, () => logic.actions.retryTraceFeedback())
            .toDispatchActions(['loadTraceFeedbackSuccess'])
            .toMatchValues({ traceFeedback: makeFeedback(), traceFeedbackFailed: false })
        expect(feedbackHints).toEqual([expectedHint, expectedHint])
    })
})

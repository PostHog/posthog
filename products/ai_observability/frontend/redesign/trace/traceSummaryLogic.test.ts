import posthog from 'posthog-js'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TraceSummaryApi } from '../../generated/api.schemas'
import { traceSummaryLogic } from './traceSummaryLogic'
import type { SummaryModeState } from './types'

const SUMMARY_URL = '/api/projects/:team_id/ai_observability/traces/:id/summary/'
const PENDING: TraceSummaryApi = { status: 'pending', content: null, failure: null }
const READY: TraceSummaryApi = {
    status: 'ready',
    content: {
        title: 'Refund request',
        bullets: [{ text: 'The user asks for a refund.', nodeId: 'gen-1' }],
        notes: [],
        flow: 'ask → refuse',
        model: 'gpt-4.1-mini',
        generatedAt: '2026-09-01T10:00:00Z',
    },
    failure: null,
}
const FAILED: TraceSummaryApi = {
    status: 'failed',
    content: null,
    failure: { reason: 'too_large', message: 'This trace is too large to summarize.' },
}

type Answer = [number, TraceSummaryApi | { detail: string }]

describe('traceSummaryLogic', () => {
    let getAnswers: Answer[]
    let getCount: number
    let postBodies: unknown[]
    let postAnswer: Answer
    let postHints: (string | null)[]

    function answerGets(...answers: Answer[]): void {
        getAnswers = answers
    }

    // The mocked API answers on timers too, so settling flushes them without moving the clock.
    async function settle(): Promise<void> {
        for (let i = 0; i < 10; i++) {
            await jest.advanceTimersByTimeAsync(0)
        }
    }

    async function advance(ms: number): Promise<void> {
        await jest.advanceTimersByTimeAsync(ms)
        await settle()
    }

    async function opened(): Promise<ReturnType<typeof traceSummaryLogic.build>> {
        const logic = traceSummaryLogic({ traceId: 'trace-1' })
        logic.mount()
        logic.actions.openSummary('tab')
        await settle()
        return logic
    }

    beforeEach(() => {
        jest.useFakeTimers()
        getAnswers = []
        getCount = 0
        postBodies = []
        postAnswer = [202, PENDING]
        postHints = []
        useMocks({
            get: {
                [SUMMARY_URL]: () => {
                    const answer = getAnswers[Math.min(getCount, getAnswers.length - 1)]
                    getCount += 1
                    return answer
                },
            },
            post: {
                [SUMMARY_URL]: async ({ request }) => {
                    postBodies.push(await request.json())
                    postHints.push(new URL(request.url).searchParams.get('timestamp_hint'))
                    return postAnswer
                },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        resumeKeaLoadersErrors()
        jest.useRealTimers()
        jest.restoreAllMocks()
    })

    it('opening shows the button when there is no summary', async () => {
        answerGets([404, { detail: 'No summary yet.' }])
        const capture = jest.spyOn(posthog, 'capture')

        const logic = await opened()

        expect(logic.values.state).toEqual({ status: 'none' })
        expect(capture).toHaveBeenCalledWith('llma trace view summary viewed', {
            has_summary: false,
            status: 'none',
            can_generate: expect.any(Boolean),
            opened_from: 'tab',
        })
    })

    it('a stored summary shows at once and is not polled', async () => {
        answerGets([200, READY])
        const capture = jest.spyOn(posthog, 'capture')

        const logic = await opened()
        await advance(30_000)

        expect(logic.values.state).toEqual({ status: 'ready', summary: READY.content })
        expect(capture).toHaveBeenCalledWith('llma trace view summary shown', { source: 'stored' })
        expect(getCount).toBe(1)
    })

    it('a request polls with backoff until the summary is ready', async () => {
        answerGets([404, { detail: 'No summary yet.' }], [200, PENDING], [200, READY])
        const capture = jest.spyOn(posthog, 'capture')
        const logic = await opened()

        logic.actions.requestSummary({ regenerate: false, timestampHint: '2026-09-01T10:00:00Z' })
        await settle()
        expect(logic.values.state).toEqual({ status: 'pending' })
        await advance(999)
        expect(getCount).toBe(1)
        await advance(1)
        expect(getCount).toBe(2)
        await advance(1499)
        expect(getCount).toBe(2)
        await advance(1)

        expect(getCount).toBe(3)
        expect(logic.values.state.status).toBe('ready')
        expect(postBodies).toEqual([{ regenerate: false }])
        expect(postHints).toEqual(['2026-09-01T10:00:00Z'])
        expect(capture).toHaveBeenCalledWith('llma trace view summary requested', { regenerate: false })
        expect(capture).toHaveBeenCalledWith('llma trace view summary shown', { source: 'just_generated' })
    })

    it('leaving the mode stops polling', async () => {
        answerGets([200, PENDING])
        const logic = await opened()

        logic.actions.closeSummary()
        await advance(30_000)

        expect(getCount).toBe(1)
    })

    it('a summary that finished while the mode was closed counts as just generated on return', async () => {
        answerGets([200, PENDING], [200, READY])
        const capture = jest.spyOn(posthog, 'capture')
        const logic = await opened()
        logic.actions.closeSummary()
        await advance(30_000)

        logic.actions.openSummary('tab')
        await settle()

        expect(logic.values.state.status).toBe('ready')
        expect(capture).toHaveBeenCalledWith('llma trace view summary shown', { source: 'just_generated' })
    })

    it('an expired pending entry shows the button again and stops polling', async () => {
        answerGets([200, PENDING], [404, { detail: 'No summary yet.' }])
        const logic = await opened()

        await advance(1000)
        await advance(30_000)

        expect(logic.values.state).toEqual({ status: 'none' })
        expect(getCount).toBe(2)
    })

    it.each<[string, Answer, SummaryModeState]>([
        ['a failed read shows the error state', [500, { detail: 'boom' }], { status: 'error' }],
        [
            'a failed job shows its message',
            [200, FAILED],
            { status: 'failed', message: 'This trace is too large to summarize.' },
        ],
    ])('%s', async (_name, answer, expected) => {
        silenceKeaLoadersErrors()
        answerGets(answer)

        const logic = await opened()

        expect(logic.values.state).toEqual(expected)
    })

    it.each([
        ['throttled', 429],
        ['failed', 500],
    ] as const)('a %s regenerate keeps the ready summary on screen and says why', async (expected, statusCode) => {
        silenceKeaLoadersErrors()
        answerGets([200, READY])
        postAnswer = [statusCode, { detail: 'nope' }]
        const logic = await opened()

        logic.actions.requestSummary({ regenerate: true, timestampHint: null })
        await settle()

        expect(logic.values.state).toEqual({ status: 'ready', summary: READY.content })
        expect(logic.values.requestError).toBe(expected)
    })
})

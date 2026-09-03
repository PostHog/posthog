import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api, { type ApiMethodOptions } from 'lib/api'
import { ApiError, NETWORK_ERROR_MESSAGES, NetworkError } from 'lib/api-error'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import type { LLMTrace } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { summaryViewLogic } from './summaryViewLogic'

describe('summaryViewLogic', () => {
    let logic: ReturnType<typeof summaryViewLogic.build>
    let createSpy: jest.SpyInstance

    const SUMMARIZATION_PATH = '/llm_analytics/summarization/'

    const trace: LLMTrace = {
        id: 'trace-1',
        createdAt: '2026-01-15T12:00:00Z',
        distinctId: 'person-1',
        events: [
            {
                id: 'gen-1',
                event: '$ai_generation',
                createdAt: '2026-01-15T12:00:00Z',
                properties: { $ai_input: [{ role: 'user', content: 'a very long prompt' }] },
            },
        ],
    }

    /** Other mounted logics post too, so only summarization requests get the test's response. */
    function mockSummarization(response: Promise<any>): void {
        createSpy.mockImplementation((url: string) =>
            url.includes(SUMMARIZATION_PATH) ? response : Promise.resolve({})
        )
    }

    function summarizationPayload(): any {
        const call = createSpy.mock.calls.find(([url]) => url.includes(SUMMARIZATION_PATH))
        return call?.[1]
    }

    /** Every `api.create` option object the summarization endpoint was called with, in order. */
    function summarizationOptions(): (ApiMethodOptions | undefined)[] {
        return createSpy.mock.calls.filter(([url]) => url.includes(SUMMARIZATION_PATH)).map((call) => call[2])
    }

    /**
     * A summarization request that settles only when its own signal aborts, the way `handleFetch`
     * rejects an aborted fetch. A shared promise that ignores the signal would let a cancellation
     * test pass without any invocation ever settling.
     */
    function summarizationPendingUntilAborted(): void {
        createSpy.mockImplementation((url: string, _data: unknown, options?: { signal?: AbortSignal }) => {
            if (!url.includes(SUMMARIZATION_PATH)) {
                return Promise.resolve({})
            }
            return new Promise((_resolve, reject) => {
                options?.signal?.addEventListener('abort', () => {
                    reject(options.signal?.reason ?? new DOMException('Aborted', 'AbortError'))
                })
            })
        })
    }

    /** Let a rejected request propagate through kea-loaders without waiting on a timer. */
    async function flushMicrotasks(): Promise<void> {
        for (let i = 0; i < 10; i++) {
            await Promise.resolve()
        }
    }

    async function generateSummary(): Promise<void> {
        logic = summaryViewLogic({ trace, tree: [] })
        logic.mount()
        await expectLogic(logic, () => {
            logic.actions.generateSummary({ mode: 'minimal' })
        }).toFinishAllListeners()
    }

    beforeEach(() => {
        silenceKeaLoadersErrors()
        initKeaTests()
        createSpy = jest.spyOn(api, 'create')
        mockSummarization(
            Promise.resolve({
                summary: { title: 'Summary', flow_diagram: '', summary_bullets: [], interesting_notes: [] },
                text_repr: 'L1 trace',
            })
        )
    })

    afterEach(() => {
        if (logic?.isMounted()) {
            logic.unmount()
        }
        jest.restoreAllMocks()
        resumeKeaLoadersErrors()
    })

    it('asks for the trace by ID instead of sending its contents', async () => {
        await generateSummary()

        expect(summarizationPayload()).toEqual({
            mode: 'minimal',
            force_refresh: false,
            trace_id: 'trace-1',
            date_from: '2026-01-14T12:00:00.000Z',
            date_to: '2026-01-16T12:00:00.000Z',
        })
    })

    test.each([
        [
            'a bodyless gateway timeout',
            () => new ApiError(undefined, 504, undefined, null),
            'Generating this summary took too long. Try again in a moment.',
        ],
        [
            'a bodyless payload-size rejection',
            () => new ApiError('API request failed with status: 413', 413),
            'This trace is too large to summarize. Open a single generation and summarize that instead.',
        ],
        [
            'a body the backend sent',
            () => new ApiError('Failed to generate summary', 413, undefined, { detail: 'Failed to generate summary' }),
            'Failed to generate summary',
        ],
        [
            'a request the browser never completed',
            () => new NetworkError('offline'),
            'Lost the connection while generating this summary. Check your connection and try again.',
        ],
    ])('shows a readable message for %s', async (_label, buildError, expected) => {
        mockSummarization(Promise.reject(buildError()))

        await generateSummary()

        expect(logic.values.summaryError).toBe(expected)
    })

    it('reports a dropped connection to error tracking as a NetworkError', async () => {
        const captureSpy = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined as any)
        mockSummarization(Promise.reject(new NetworkError('offline')))

        await generateSummary()

        // `dropUnactionableNetworkExceptions` matches the name and the message, so rewriting either
        // one files an issue for a failure the platform already treats as unactionable.
        // Mounting already asks for a cached summary, so that request fails here too. Assert the
        // call happened rather than a count, so an empty spy fails on the expectation.
        expect(captureSpy).toHaveBeenCalled()
        const reported = captureSpy.mock.calls[0]?.[0] as Error
        expect(reported.name).toBe('NetworkError')
        expect(reported.message).toBe(NETWORK_ERROR_MESSAGES.offline)
    })

    it('keeps the panel loading when a newer summary replaces an in-flight one', async () => {
        summarizationPendingUntilAborted()
        logic = summaryViewLogic({ trace, tree: [] })
        logic.mount()

        logic.actions.generateSummary({ mode: 'minimal' })
        await flushMicrotasks()
        logic.actions.generateSummary({ mode: 'detailed' })
        await flushMicrotasks()

        // Mounting already asks for a cached summary, so compare the last two requests.
        const [previous, latest] = summarizationOptions().slice(-2)
        expect(previous?.signal?.aborted).toBe(true)
        expect(latest?.signal?.aborted).toBe(false)
        // The cancelled request must not settle the loader. SummaryViewDisplay shows its empty
        // state on `!summaryData && !summaryDataLoading && !summaryError`, so a cleared flag
        // replaces the running summary with "Generate an AI-powered summary of this trace".
        expect(logic.values.summaryDataLoading).toBe(true)
        expect(logic.values.summaryError).toBeNull()
    })

    it('keeps the cancellation reason out of the panel', async () => {
        await generateSummary()

        // A cancellation that reaches the reducer carries the internal sentinel as its message.
        // Only the breakpoint keeps a superseded request from getting here, so the guard is what
        // stops that sentinel reaching the panel for any other cancellation.
        const cancellation = new DOMException('a newer summary request started', 'AbortError')
        logic.actions.generateSummaryFailure(cancellation.message, cancellation)

        expect(logic.values.summaryError).toBeNull()
    })

    it('cancels an in-flight request when the trace view closes', async () => {
        summarizationPendingUntilAborted()
        logic = summaryViewLogic({ trace, tree: [] })
        logic.mount()
        logic.actions.generateSummary({ mode: 'minimal' })
        await flushMicrotasks()

        logic.unmount()

        expect(summarizationOptions().at(-1)?.signal?.aborted).toBe(true)
    })

    it('clears a stale summary when regeneration fails', async () => {
        await generateSummary()
        expect(logic.values.summaryData?.summary.title).toBe('Summary')
        mockSummarization(Promise.reject(new Error('Regeneration failed')))

        await expectLogic(logic, () => {
            logic.actions.regenerateSummary()
        }).toFinishAllListeners()

        expect(logic.values.summaryData).toBeNull()
        expect(logic.values.summaryError).toBe('Regeneration failed')
    })
})

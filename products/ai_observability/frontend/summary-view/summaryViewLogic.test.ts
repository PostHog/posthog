import { expectLogic } from 'kea-test-utils'

import api from 'lib/api'
import { ApiError } from 'lib/api-error'

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
        logic?.unmount()
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

    it('shows a readable message when the response carries no error body', async () => {
        mockSummarization(Promise.reject(new ApiError(undefined, 504, undefined, null)))

        await generateSummary()

        expect(logic.values.summaryError).toBe('Generating this summary took too long. Try again in a moment.')
    })

    it('maps a bodyless payload-size rejection to a readable message, not a bare status', async () => {
        mockSummarization(Promise.reject(new ApiError('API request failed with status: 413', 413)))

        await generateSummary()

        expect(logic.values.summaryError).not.toContain('413')
        expect(logic.values.summaryError).toBe(
            'This trace is too large to summarize. Open a single generation and summarize that instead.'
        )
    })

    it('keeps a response body the backend sent instead of guessing from the status', async () => {
        mockSummarization(
            Promise.reject(
                new ApiError('Failed to generate summary', 413, undefined, { detail: 'Failed to generate summary' })
            )
        )

        await generateSummary()

        expect(logic.values.summaryError).toBe('Failed to generate summary')
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

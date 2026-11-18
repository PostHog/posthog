import api from '~/lib/api'
import { initKeaTests } from '~/test/init'

import { aiObservabilityAIDataLogic } from './aiObservabilityAIDataLogic'

jest.mock('~/lib/api')

const mockApi = api as jest.Mocked<typeof api>

// A row as the heavy-prop query returns it:
// [uuid, input, output, output_choices, input_state, output_state, tools].
type Row = [string, unknown, unknown, unknown, unknown, unknown, unknown]

// Let the listener's setTimeout(0) batch timer fire, then take one more macrotask turn so the
// query + merge chain settles regardless of its await depth.
async function settle(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0))
    await new Promise((resolve) => setTimeout(resolve, 0))
}

describe('aiObservabilityAIDataLogic', () => {
    let logic: ReturnType<typeof aiObservabilityAIDataLogic.build>

    beforeEach(() => {
        jest.resetAllMocks()
        initKeaTests()
        logic = aiObservabilityAIDataLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('passes through when both input and output are already present — no heavy-prop lookup', async () => {
        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: [{ role: 'user', content: 'hi' }],
                output: [{ role: 'assistant', content: 'hello' }],
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            },
        ])
        await settle()

        expect(logic.values.aiDataCache).toEqual({
            'event-1': {
                input: [{ role: 'user', content: 'hi' }],
                output: [{ role: 'assistant', content: 'hello' }],
                tools: undefined,
            },
        })
        expect(logic.values.isEventLoading('event-1')).toBe(false)
        expect(mockApi.queryHogQL).not.toHaveBeenCalled()
    })

    it('fetches from ai_events and populates heavy props when input is missing', async () => {
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValue({
            results: [
                [
                    'event-1',
                    JSON.stringify([{ role: 'user', content: 'post-strip hi' }]),
                    null,
                    JSON.stringify([{ role: 'assistant', content: 'post-strip hello' }]),
                    null,
                    null,
                    JSON.stringify([{ function: { name: 'search' } }]),
                ] as Row,
            ],
        } as any)

        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            },
        ])
        await settle()

        expect(logic.values.aiDataCache['event-1']).toEqual({
            input: [{ role: 'user', content: 'post-strip hi' }],
            output: [{ role: 'assistant', content: 'post-strip hello' }],
            tools: [{ function: { name: 'search' } }],
        })
        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(1)
        expect(mockApi.queryHogQL.mock.calls[0][0]).toContain('FROM posthog.ai_events AS ai_events')
    })

    it('falls back to events when ai_events has no heavy props row', async () => {
        jest.spyOn(mockApi, 'queryHogQL')
            .mockResolvedValueOnce({ results: [] } as any)
            .mockResolvedValueOnce({
                results: [
                    [
                        'event-1',
                        [{ role: 'user', content: 'events hi' }],
                        null,
                        [{ role: 'assistant', content: 'events hello' }],
                        null,
                        null,
                        [{ function: { name: 'events-search' } }],
                    ] as Row,
                ],
            } as any)

        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            },
        ])
        await settle()

        expect(logic.values.aiDataCache['event-1']).toEqual({
            input: [{ role: 'user', content: 'events hi' }],
            output: [{ role: 'assistant', content: 'events hello' }],
            tools: [{ function: { name: 'events-search' } }],
        })
        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(2)
        expect(mockApi.queryHogQL.mock.calls[0][0]).toContain('FROM posthog.ai_events AS ai_events')
        expect(mockApi.queryHogQL.mock.calls[1][0]).toContain('FROM events')
    })

    it('prefers populated input_state over an empty input array and keeps an empty output as arrived', async () => {
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValue({
            results: [
                [
                    'event-1',
                    '[]',
                    null,
                    '[]',
                    JSON.stringify({ messages: [{ type: 'human', content: 'state input' }] }),
                    null,
                    null,
                ] as Row,
            ],
        } as any)

        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            },
        ])
        await settle()

        expect(logic.values.aiDataCache['event-1']).toEqual({
            input: { messages: [{ type: 'human', content: 'state input' }] },
            output: [],
            tools: undefined,
        })
        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(1)
    })

    it('parses fetched heavy props in full instead of collapsing them into a truncated preview', async () => {
        const fullInput = [
            { role: 'system', content: `You are a data extraction specialist. ${'detail '.repeat(60)}` },
            { role: 'user', content: 'analyze this page' },
        ]
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValue({
            results: [['event-1', JSON.stringify(fullInput), null, null, null, null, null] as Row],
        } as any)

        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: fullInput,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            },
        ])
        await settle()

        expect(logic.values.aiDataCache['event-1']).toEqual({
            input: fullInput,
            output: undefined,
            tools: undefined,
        })
    })

    it('resolves the cell and clears loading when the lookup finds nothing', async () => {
        // Regression: an unresolved row must not stay pinned in the loading set forever.
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValue({ results: [] } as any)

        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: 'fallback-input',
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            },
        ])
        await settle()

        expect(logic.values.aiDataCache).toHaveProperty('event-1')
        expect(logic.values.aiDataCache['event-1']).toEqual({
            input: 'fallback-input',
            output: undefined,
            tools: undefined,
        })
        expect(logic.values.isEventLoading('event-1')).toBe(false)
    })

    it('degrades gracefully and clears loading when both sources throw', async () => {
        // Regression: the failure path used to read the event id from the thrown error, so the
        // row was never removed from the loading set and the cell loaded forever.
        jest.spyOn(mockApi, 'queryHogQL').mockRejectedValue(new Error('network down'))
        const warnSpy = jest.spyOn(console, 'warn').mockImplementation()

        try {
            logic.actions.ensureAIDataLoaded([
                {
                    eventId: 'event-1',
                    input: 'fallback-input',
                    output: undefined,
                    tools: undefined,
                    traceId: 'trace-1',
                    timestamp: '2026-04-30T10:00:00Z',
                },
            ])
            await settle()

            expect(logic.values.aiDataCache['event-1']).toEqual({
                input: 'fallback-input',
                output: undefined,
                tools: undefined,
            })
            expect(logic.values.isEventLoading('event-1')).toBe(false)
            expect(warnSpy).toHaveBeenCalledWith(
                '[aiObservabilityAIDataLogic] failed to load heavy AI props from ai_events',
                expect.any(Error)
            )
            expect(warnSpy).toHaveBeenCalledWith(
                '[aiObservabilityAIDataLogic] failed to load heavy AI props from events',
                expect.any(Error)
            )
        } finally {
            warnSpy.mockRestore()
        }
    })

    it('loads many rows with a single query per source instead of one query per row', async () => {
        // Regression: the previous implementation fired one HogQL query per visible row.
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValue({
            results: [
                ['event-1', JSON.stringify(['in-1']), JSON.stringify(['out-1']), null, null, null, null] as Row,
                ['event-2', JSON.stringify(['in-2']), JSON.stringify(['out-2']), null, null, null, null] as Row,
            ],
        } as any)

        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            },
            {
                eventId: 'event-2',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:05:00Z',
            },
        ])
        await settle()

        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(1)
        expect(logic.values.aiDataCache['event-1']).toEqual({ input: ['in-1'], output: ['out-1'], tools: undefined })
        expect(logic.values.aiDataCache['event-2']).toEqual({ input: ['in-2'], output: ['out-2'], tools: undefined })
    })

    it.each([
        ['traceId missing', { traceId: undefined, timestamp: '2026-04-30T10:00:00Z' }],
        ['timestamp missing', { traceId: 'trace-1', timestamp: undefined }],
        ['both missing', { traceId: undefined, timestamp: undefined }],
    ])('skips the fetch when trace coordinates are incomplete (%s)', async (_label, coords) => {
        const querySpy = jest.spyOn(mockApi, 'queryHogQL')

        logic.actions.ensureAIDataLoaded([
            {
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                ...coords,
            },
        ])
        await settle()

        expect(querySpy).not.toHaveBeenCalled()
        // Still resolved, so the cell stops loading and falls back to the main-query values.
        expect(logic.values.aiDataCache).toHaveProperty('event-1')
        expect(logic.values.isEventLoading('event-1')).toBe(false)
    })
})

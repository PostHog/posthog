import { expectLogic } from 'kea-test-utils'

import api from '~/lib/api'
import { initKeaTests } from '~/test/init'

import { aiObservabilityAIDataLogic } from './aiObservabilityAIDataLogic'

jest.mock('~/lib/api')

const mockApi = api as jest.Mocked<typeof api>

describe('aiObservabilityAIDataLogic', () => {
    beforeEach(() => {
        jest.resetAllMocks()
        initKeaTests()
    })

    it('passes through when both input and output are already present — no heavy-prop lookup', async () => {
        const logic = aiObservabilityAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: [{ role: 'user', content: 'hi' }],
                output: [{ role: 'assistant', content: 'hello' }],
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiDataCache: {
                    'event-1': {
                        input: [{ role: 'user', content: 'hi' }],
                        output: [{ role: 'assistant', content: 'hello' }],
                        tools: undefined,
                    },
                },
            })

        expect(mockApi.query).not.toHaveBeenCalled()
        expect(mockApi.queryHogQL).not.toHaveBeenCalled()
    })

    it('fetches from ai_events and populates heavy props when input is missing', async () => {
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValue({
            results: [
                [
                    JSON.stringify([{ role: 'user', content: 'post-strip hi' }]),
                    null,
                    JSON.stringify([{ role: 'assistant', content: 'post-strip hello' }]),
                    null,
                    null,
                    JSON.stringify([{ function: { name: 'search' } }]),
                ],
            ],
        } as any)

        const logic = aiObservabilityAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiDataCache: {
                    'event-1': {
                        input: [{ role: 'user', content: 'post-strip hi' }],
                        output: [{ role: 'assistant', content: 'post-strip hello' }],
                        tools: [{ function: { name: 'search' } }],
                    },
                },
            })

        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(1)
        expect(mockApi.queryHogQL.mock.calls[0][0]).toContain('FROM posthog.ai_events AS ai_events')
        expect(mockApi.query).not.toHaveBeenCalled()
    })

    it('falls back to events when ai_events has no heavy props row', async () => {
        jest.spyOn(mockApi, 'queryHogQL')
            .mockResolvedValueOnce({ results: [] } as any)
            .mockResolvedValueOnce({
                results: [
                    [
                        [{ role: 'user', content: 'events hi' }],
                        null,
                        [{ role: 'assistant', content: 'events hello' }],
                        null,
                        null,
                        [{ function: { name: 'events-search' } }],
                    ],
                ],
            } as any)

        const logic = aiObservabilityAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiDataCache: {
                    'event-1': {
                        input: [{ role: 'user', content: 'events hi' }],
                        output: [{ role: 'assistant', content: 'events hello' }],
                        tools: [{ function: { name: 'events-search' } }],
                    },
                },
            })

        expect(mockApi.queryHogQL).toHaveBeenCalledTimes(2)
        expect(mockApi.queryHogQL.mock.calls[0][0]).toContain('FROM posthog.ai_events AS ai_events')
        expect(mockApi.queryHogQL.mock.calls[1][0]).toContain('FROM events')
    })

    it('parses fetched heavy props in full instead of collapsing them into a truncated preview', async () => {
        const fullInput = [
            { role: 'system', content: `You are a data extraction specialist. ${'detail '.repeat(60)}` },
            { role: 'user', content: 'analyze this page' },
        ]
        jest.spyOn(mockApi, 'queryHogQL').mockResolvedValue({
            results: [[JSON.stringify(fullInput), null, null, null, null, null]],
        } as any)

        const logic = aiObservabilityAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: fullInput,
                output: undefined,
                tools: undefined,
                traceId: 'trace-1',
                timestamp: '2026-04-30T10:00:00Z',
            })
        })
            .toFinishAllListeners()
            .toMatchValues({
                aiDataCache: {
                    'event-1': {
                        input: fullInput,
                        output: undefined,
                        tools: undefined,
                    },
                },
            })
    })

    it('degrades gracefully to the passed-in values when the lookup throws', async () => {
        jest.spyOn(mockApi, 'queryHogQL').mockRejectedValue(new Error('network down'))
        // The logic warns (by design) once per failed source before falling back.
        const warnSpy = jest.spyOn(console, 'warn').mockImplementation()

        try {
            const logic = aiObservabilityAIDataLogic()
            logic.mount()

            await expectLogic(logic, () => {
                logic.actions.loadAIDataForEvent({
                    eventId: 'event-1',
                    input: 'fallback-input',
                    output: undefined,
                    tools: undefined,
                    traceId: 'trace-1',
                    timestamp: '2026-04-30T10:00:00Z',
                })
            })
                .toFinishAllListeners()
                .toMatchValues({
                    aiDataCache: {
                        'event-1': {
                            input: 'fallback-input',
                            output: undefined,
                            tools: undefined,
                        },
                    },
                })

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

    it.each([
        ['traceId missing', { traceId: undefined, timestamp: '2026-04-30T10:00:00Z' }],
        ['timestamp missing', { traceId: 'trace-1', timestamp: undefined }],
        ['both missing', { traceId: undefined, timestamp: undefined }],
    ])('skips the fetch when trace coordinates are incomplete (%s)', async (_label, coords) => {
        const querySpy = jest.spyOn(mockApi, 'queryHogQL')

        const logic = aiObservabilityAIDataLogic()
        logic.mount()

        await expectLogic(logic, () => {
            logic.actions.loadAIDataForEvent({
                eventId: 'event-1',
                input: undefined,
                output: undefined,
                tools: undefined,
                ...coords,
            })
        }).toFinishAllListeners()

        expect(querySpy).not.toHaveBeenCalled()
    })
})

import { Message } from 'node-rdkafka'

import { createAiGenerationEvent } from '~/llm-analytics/_tests/fixtures'

import { TemporalService } from '../llm-analytics/services/temporal.service'
import {
    SampleRateProvider,
    checkSampleRate,
    chunk,
    eachBatchSentimentScheduler,
    filterAndParseMessages,
    parseSampleRatePayload,
    parseTeamAllowlist,
} from './sentiment-scheduler'

jest.mock('~/llm-analytics/services/temporal.service')

describe('Sentiment Scheduler', () => {
    const teamId = 1

    describe('filterAndParseMessages', () => {
        it('filters messages by productTrack header and parses JSON', () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('general') }],
                    value: Buffer.from(JSON.stringify({ event: '$pageview', team_id: teamId })),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            const result = filterAndParseMessages(messages)

            expect(result).toHaveLength(2)
            result.forEach((event) => expect(event.event).toBe('$ai_generation'))
        })

        it('handles malformed JSON gracefully', () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from('invalid json{'),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            const result = filterAndParseMessages(messages)

            expect(result).toHaveLength(1)
        })

        it('filters out non-llma messages', () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('general') }],
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                } as any,
                {
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                } as any,
            ]

            const result = filterAndParseMessages(messages)

            expect(result).toHaveLength(0)
        })

        it('filters out non-$ai_generation events', () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify({ ...createAiGenerationEvent(teamId), event: '$ai_trace' })),
                } as any,
            ]

            const result = filterAndParseMessages(messages)

            expect(result).toHaveLength(0)
        })
    })

    describe('checkSampleRate', () => {
        it('always includes when sample rate is 1.0 (100%)', () => {
            expect(checkSampleRate('event-1', 1.0)).toBe(true)
            expect(checkSampleRate('event-2', 1.0)).toBe(true)
            expect(checkSampleRate('any-event', 1.0)).toBe(true)
        })

        it('always includes when sample rate is above 1.0', () => {
            expect(checkSampleRate('event-1', 1.5)).toBe(true)
        })

        it('always excludes when sample rate is 0', () => {
            expect(checkSampleRate('event-1', 0)).toBe(false)
            expect(checkSampleRate('event-2', 0)).toBe(false)
        })

        it('always excludes when sample rate is negative', () => {
            expect(checkSampleRate('event-1', -0.5)).toBe(false)
        })

        it('is deterministic for same event id', () => {
            const result1 = checkSampleRate('event-123', 0.5)
            const result2 = checkSampleRate('event-123', 0.5)
            expect(result1).toBe(result2)
        })

        it('includes roughly correct percentage of events at 10%', () => {
            const testEventIds = Array.from({ length: 10000 }, (_, i) => `event-${i}`)
            const included = testEventIds.filter((eventId) => checkSampleRate(eventId, 0.1))

            // Should be roughly 10%, allow 2% variance
            expect(included.length).toBeGreaterThan(800)
            expect(included.length).toBeLessThan(1200)
        })

        it('includes roughly correct percentage of events at 1%', () => {
            const testEventIds = Array.from({ length: 100000 }, (_, i) => `event-${i}`)
            const included = testEventIds.filter((eventId) => checkSampleRate(eventId, 0.01))

            // Should be roughly 1%, allow 0.5% variance
            expect(included.length).toBeGreaterThan(500)
            expect(included.length).toBeLessThan(1500)
        })
    })

    describe('chunk', () => {
        it.each([
            [
                'splits evenly',
                [1, 2, 3, 4],
                2,
                [
                    [1, 2],
                    [3, 4],
                ],
            ],
            ['handles remainder', [1, 2, 3], 2, [[1, 2], [3]]],
            ['single chunk when under size', [1, 2], 5, [[1, 2]]],
            ['empty array', [], 3, []],
            ['size of 1', [1, 2, 3], 1, [[1], [2], [3]]],
        ])('%s', (_label, input, size, expected) => {
            expect(chunk(input, size)).toEqual(expected)
        })
    })

    describe('parseTeamAllowlist', () => {
        it.each([
            ['empty string', '', null],
            ['whitespace only', '  ', null],
            ['single team', '2', new Set([2])],
            ['multiple teams', '2,5,10', new Set([2, 5, 10])],
            ['with whitespace', ' 2 , 5 ', new Set([2, 5])],
            ['ignores non-numeric', 'abc,2,def', new Set([2])],
            ['all non-numeric', 'abc,def', null],
        ])('%s: %s', (_label, input, expected) => {
            expect(parseTeamAllowlist(input)).toEqual(expected)
        })
    })

    describe('parseSampleRatePayload', () => {
        const fallback = 0.01

        it.each([
            ['JSON string with valid rate', '{"sample_rate": 0.5}', 0.5],
            ['JSON string with zero rate', '{"sample_rate": 0}', 0],
            ['JSON string with 1.0 rate', '{"sample_rate": 1.0}', 1.0],
            ['object with valid rate', { sample_rate: 0.25 }, 0.25],
        ])('parses %s', (_label, payload, expected) => {
            expect(parseSampleRatePayload(payload, fallback)).toBe(expected)
        })

        it.each([
            ['null', null],
            ['undefined', undefined],
            ['invalid JSON string', 'not-json'],
            ['missing sample_rate key', '{"other": 0.5}'],
            ['NaN sample_rate', '{"sample_rate": "abc"}'],
            ['negative sample_rate', '{"sample_rate": -0.5}'],
            ['sample_rate > 1', '{"sample_rate": 1.5}'],
            ['non-object type', 42],
        ])('returns fallback for %s', (_label, payload) => {
            expect(parseSampleRatePayload(payload, fallback)).toBe(fallback)
        })
    })

    describe('SampleRateProvider', () => {
        it('uses fallback rate when no API key is provided', async () => {
            const provider = new SampleRateProvider(0.05)
            await provider.start()

            expect(provider.getSampleRate()).toBe(0.05)

            await provider.stop()
        })
    })

    describe('eachBatchSentimentScheduler', () => {
        let mockTemporalService: jest.Mocked<TemporalService>
        let sampleRateProvider: SampleRateProvider

        beforeEach(async () => {
            mockTemporalService = {
                startSentimentClassificationWorkflow: jest.fn().mockResolvedValue({ workflowId: 'test' }),
                disconnect: jest.fn(),
            } as any

            sampleRateProvider = new SampleRateProvider(1.0)
            await sampleRateProvider.start()
        })

        afterEach(async () => {
            await sampleRateProvider.stop()
        })

        it('starts one batch workflow with all sampled events', async () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, mockTemporalService, sampleRateProvider)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
            const callArgs = mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]
            expect(callArgs).toHaveLength(3)
        })

        it('does not start workflow when no events pass sampling', async () => {
            const zeroRateProvider = new SampleRateProvider(0)
            await zeroRateProvider.start()

            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, mockTemporalService, zeroRateProvider)

            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()

            await zeroRateProvider.stop()
        })

        it('does not start workflow when no llma events in batch', async () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('general') }],
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, mockTemporalService, sampleRateProvider)

            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()
        })

        it('filters events by team allowlist', async () => {
            const allowedTeamId = 2
            const blockedTeamId = 99
            const teamAllowlist = new Set([allowedTeamId])

            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(allowedTeamId))),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(blockedTeamId))),
                } as any,
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(allowedTeamId))),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, mockTemporalService, sampleRateProvider, teamAllowlist)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
            const callArgs = mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]
            expect(callArgs).toHaveLength(2)
            callArgs.forEach((event: any) => expect(event.team_id).toBe(allowedTeamId))
        })

        it('skips batch when all events are from non-allowed teams', async () => {
            const teamAllowlist = new Set([2])

            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(99))),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, mockTemporalService, sampleRateProvider, teamAllowlist)

            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()
        })

        it('allows all teams when allowlist is null', async () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(99))),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, mockTemporalService, sampleRateProvider, null)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
        })

        it('splits sampled events into batches by batchSize', async () => {
            const messages: Message[] = Array.from({ length: 5 }, () => ({
                headers: [{ productTrack: Buffer.from('llma') }],
                value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
            })) as any[]

            await eachBatchSentimentScheduler(messages, mockTemporalService, sampleRateProvider, null, 2)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(3)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]).toHaveLength(2)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[1][0]).toHaveLength(2)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[2][0]).toHaveLength(1)
        })

        it('handles workflow start failure gracefully', async () => {
            mockTemporalService.startSentimentClassificationWorkflow.mockRejectedValue(
                new Error('Temporal unavailable')
            )

            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            // Should not throw
            await eachBatchSentimentScheduler(messages, mockTemporalService, sampleRateProvider)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
        })
    })
})

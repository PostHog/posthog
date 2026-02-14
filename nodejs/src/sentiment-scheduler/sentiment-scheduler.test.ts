import { Message } from 'node-rdkafka'

import { createAiGenerationEvent } from '~/llm-analytics/_tests/fixtures'

import { TemporalService } from '../llm-analytics/services/temporal.service'
import {
    SampleRateProvider,
    SentimentBatchBuffer,
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

    describe('SentimentBatchBuffer', () => {
        let mockTemporalService: jest.Mocked<TemporalService>

        beforeEach(() => {
            mockTemporalService = {
                startSentimentClassificationWorkflow: jest.fn().mockResolvedValue({ workflowId: 'test' }),
                disconnect: jest.fn(),
            } as any
        })

        it('flushes immediately when buffer reaches batchSize', async () => {
            const buffer = new SentimentBatchBuffer(mockTemporalService, 3, 60_000)
            buffer.start()

            const events = Array.from({ length: 3 }, () => createAiGenerationEvent(teamId))
            await buffer.add(events)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]).toHaveLength(3)
            expect(buffer.getBufferSize()).toBe(0)

            await buffer.stop()
        })

        it('does not flush when buffer is under batchSize', async () => {
            const buffer = new SentimentBatchBuffer(mockTemporalService, 5, 60_000)
            buffer.start()

            const events = Array.from({ length: 3 }, () => createAiGenerationEvent(teamId))
            await buffer.add(events)

            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()
            expect(buffer.getBufferSize()).toBe(3)

            await buffer.stop()
        })

        it('accumulates events across multiple add() calls', async () => {
            const buffer = new SentimentBatchBuffer(mockTemporalService, 5, 60_000)
            buffer.start()

            await buffer.add([createAiGenerationEvent(teamId), createAiGenerationEvent(teamId)])
            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()

            await buffer.add([
                createAiGenerationEvent(teamId),
                createAiGenerationEvent(teamId),
                createAiGenerationEvent(teamId),
            ])
            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]).toHaveLength(5)
            expect(buffer.getBufferSize()).toBe(0)

            await buffer.stop()
        })

        it('handles overflow by dispatching multiple batches', async () => {
            const buffer = new SentimentBatchBuffer(mockTemporalService, 3, 60_000)
            buffer.start()

            const events = Array.from({ length: 7 }, () => createAiGenerationEvent(teamId))
            await buffer.add(events)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(2)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]).toHaveLength(3)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[1][0]).toHaveLength(3)
            expect(buffer.getBufferSize()).toBe(1)

            await buffer.stop()
        })

        it('flushes remaining events on stop', async () => {
            const buffer = new SentimentBatchBuffer(mockTemporalService, 10, 60_000)
            buffer.start()

            await buffer.add([createAiGenerationEvent(teamId), createAiGenerationEvent(teamId)])
            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()

            await buffer.stop()

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]).toHaveLength(2)
        })

        it('flushes on timer interval', async () => {
            jest.useFakeTimers()

            const buffer = new SentimentBatchBuffer(mockTemporalService, 100, 5_000)
            buffer.start()

            await buffer.add([createAiGenerationEvent(teamId)])
            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()

            jest.advanceTimersByTime(5_000)
            await Promise.resolve()

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]).toHaveLength(1)
            expect(buffer.getBufferSize()).toBe(0)

            await buffer.stop()
            jest.useRealTimers()
        })

        it('does not flush on timer when buffer is empty', async () => {
            jest.useFakeTimers()

            const buffer = new SentimentBatchBuffer(mockTemporalService, 100, 5_000)
            buffer.start()

            jest.advanceTimersByTime(5_000)
            await Promise.resolve()

            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()

            await buffer.stop()
            jest.useRealTimers()
        })
    })

    describe('eachBatchSentimentScheduler', () => {
        let mockTemporalService: jest.Mocked<TemporalService>
        let sampleRateProvider: SampleRateProvider
        let batchBuffer: SentimentBatchBuffer

        beforeEach(async () => {
            mockTemporalService = {
                startSentimentClassificationWorkflow: jest.fn().mockResolvedValue({ workflowId: 'test' }),
                disconnect: jest.fn(),
            } as any

            sampleRateProvider = new SampleRateProvider(1.0)
            await sampleRateProvider.start()

            batchBuffer = new SentimentBatchBuffer(mockTemporalService, 100, 60_000)
            batchBuffer.start()
        })

        afterEach(async () => {
            await batchBuffer.stop()
            await sampleRateProvider.stop()
        })

        it('adds sampled events to the buffer', async () => {
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

            await eachBatchSentimentScheduler(messages, batchBuffer, sampleRateProvider)

            expect(batchBuffer.getBufferSize()).toBe(3)
            expect(mockTemporalService.startSentimentClassificationWorkflow).not.toHaveBeenCalled()
        })

        it('does not buffer when no events pass sampling', async () => {
            const zeroRateProvider = new SampleRateProvider(0)
            await zeroRateProvider.start()

            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('llma') }],
                    value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, batchBuffer, zeroRateProvider)

            expect(batchBuffer.getBufferSize()).toBe(0)

            await zeroRateProvider.stop()
        })

        it('does not buffer when no llma events in batch', async () => {
            const messages: Message[] = [
                {
                    headers: [{ productTrack: Buffer.from('general') }],
                    value: Buffer.from(JSON.stringify({ event: '$pageview' })),
                } as any,
            ]

            await eachBatchSentimentScheduler(messages, batchBuffer, sampleRateProvider)

            expect(batchBuffer.getBufferSize()).toBe(0)
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

            await eachBatchSentimentScheduler(messages, batchBuffer, sampleRateProvider, teamAllowlist)

            expect(batchBuffer.getBufferSize()).toBe(2)
        })

        it('triggers immediate flush when buffer reaches batchSize', async () => {
            const smallBuffer = new SentimentBatchBuffer(mockTemporalService, 2, 60_000)
            smallBuffer.start()

            const messages: Message[] = Array.from({ length: 3 }, () => ({
                headers: [{ productTrack: Buffer.from('llma') }],
                value: Buffer.from(JSON.stringify(createAiGenerationEvent(teamId))),
            })) as any[]

            await eachBatchSentimentScheduler(messages, smallBuffer, sampleRateProvider)

            expect(mockTemporalService.startSentimentClassificationWorkflow).toHaveBeenCalledTimes(1)
            expect(mockTemporalService.startSentimentClassificationWorkflow.mock.calls[0][0]).toHaveLength(2)
            expect(smallBuffer.getBufferSize()).toBe(1)

            await smallBuffer.stop()
        })
    })
})

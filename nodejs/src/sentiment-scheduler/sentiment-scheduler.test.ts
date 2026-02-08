import { Message } from 'node-rdkafka'

import { createAiGenerationEvent } from '~/llm-analytics/_tests/fixtures'

import {
    SampleRateProvider,
    checkSampleRate,
    filterAndParseMessages,
    parseSampleRatePayload,
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
})

import { Message } from 'node-rdkafka'

import { createAiGenerationEvent } from '~/llm-analytics/_tests/fixtures'

import { checkSampleRate, filterAndParseMessages } from './sentiment-scheduler'

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
})

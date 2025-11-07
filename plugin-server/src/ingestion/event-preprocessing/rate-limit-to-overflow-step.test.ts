import { Message } from 'node-rdkafka'

import { PipelineEvent } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { MemoryRateLimiter } from '../utils/overflow-detector'
import { createRateLimitToOverflowStep } from './rate-limit-to-overflow-step'

describe('createRateLimitToOverflowStep', () => {
    const createMockMessage = (timestamp: number = Date.now()): Message => ({
        value: Buffer.from('test'),
        size: 4,
        topic: 'events_plugin_ingestion',
        offset: 1,
        partition: 0,
        key: null,
        timestamp,
    })

    const createMockEvent = (token: string, distinctId: string, timestamp?: number) => ({
        message: createMockMessage(timestamp),
        event: {
            token,
            distinct_id: distinctId,
            event: '$pageview',
            properties: {},
        } as PipelineEvent,
    })

    describe('when overflow is disabled', () => {
        it('should return all events as ok', async () => {
            const rateLimiter = new MemoryRateLimiter(100, 10)
            const step = createRateLimitToOverflowStep(rateLimiter, false, 'overflow_topic', true)

            const events = [
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user2'),
                createMockEvent('token2', 'user1'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(3)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })
    })

    describe('when overflow is enabled', () => {
        it('should return ok for events below rate limit', async () => {
            const rateLimiter = new MemoryRateLimiter(100, 10)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [createMockEvent('token1', 'user1'), createMockEvent('token1', 'user2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('should redirect events that exceed rate limit', async () => {
            const rateLimiter = new MemoryRateLimiter(5, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            // Create 10 events for the same key (will exceed limit of 5)
            const events = Array.from({ length: 10 }, () => createMockEvent('token1', 'user1'))

            const results = await step(events)

            expect(results).toHaveLength(10)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.REDIRECT)
                if (result.type === PipelineResultType.REDIRECT) {
                    expect(result.reason).toBe('rate_limit_exceeded')
                    expect(result.topic).toBe('overflow_topic')
                }
            })
        })

        it('should group events by token:distinct_id key', async () => {
            const rateLimiter = new MemoryRateLimiter(2, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [
                // 2 events for token1:user1 (at limit)
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                // 2 events for token1:user2 (at limit)
                createMockEvent('token1', 'user2'),
                createMockEvent('token1', 'user2'),
                // 2 events for token2:user1 (at limit)
                createMockEvent('token2', 'user1'),
                createMockEvent('token2', 'user1'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(6)
            // All should be ok since each key has exactly 2 events (at the limit)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('should redirect only keys that exceed limit, not others', async () => {
            const rateLimiter = new MemoryRateLimiter(2, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [
                // 3 events for token1:user1 (exceeds limit of 2)
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                // 1 event for token1:user2 (below limit)
                createMockEvent('token1', 'user2'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(4)

            // First 3 should be redirected (token1:user1 exceeded)
            for (let i = 0; i < 3; i++) {
                expect(results[i].type).toBe(PipelineResultType.REDIRECT)
            }

            // Last 1 should be ok (token1:user2 below limit)
            expect(results[3].type).toBe(PipelineResultType.OK)
        })

        it('should handle empty token or distinct_id', async () => {
            const rateLimiter = new MemoryRateLimiter(5, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [createMockEvent('', 'user1'), createMockEvent('token1', ''), createMockEvent('', '')]

            const results = await step(events)

            expect(results).toHaveLength(3)
            // Should not crash and should group by empty strings
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('should use kafka timestamp for rate limiting', async () => {
            const rateLimiter = new MemoryRateLimiter(2, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const baseTime = Date.now()

            const events = [
                // 2 events at time T (at limit)
                createMockEvent('token1', 'user1', baseTime),
                createMockEvent('token1', 'user1', baseTime),
            ]

            const results = await step(events)

            expect(results).toHaveLength(2)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('should preserve input structure in results', async () => {
            const rateLimiter = new MemoryRateLimiter(100, 10)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [
                {
                    ...createMockEvent('token1', 'user1'),
                    additionalField: 'test',
                },
            ]

            const results = await step(events)

            expect(results).toHaveLength(1)
            expect(results[0].type).toBe(PipelineResultType.OK)
            if (results[0].type === PipelineResultType.OK) {
                expect(results[0].value).toHaveProperty('additionalField', 'test')
            }
        })

        it('should maintain ordering of events in results', async () => {
            const rateLimiter = new MemoryRateLimiter(100, 10)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [
                createMockEvent('token1', 'user1'),
                createMockEvent('token2', 'user2'),
                createMockEvent('token3', 'user3'),
                createMockEvent('token1', 'user1'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(4)

            // Verify the order is maintained by checking the results correspond to original events
            for (let i = 0; i < results.length; i++) {
                const result = results[i]
                if (result.type === PipelineResultType.OK) {
                    expect(result.value.event.token).toBe(events[i].event.token)
                    expect(result.value.event.distinct_id).toBe(events[i].event.distinct_id)
                }
            }
        })

        it('should preserve partition key when preservePartitionLocality is true', async () => {
            const rateLimiter = new MemoryRateLimiter(1, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'), // Will exceed limit
            ]

            const results = await step(events)

            expect(results).toHaveLength(2)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.REDIRECT)
                if (result.type === PipelineResultType.REDIRECT) {
                    expect(result.preserveKey).toBe(true)
                }
            })
        })

        it('should not preserve partition key when preservePartitionLocality is false', async () => {
            const rateLimiter = new MemoryRateLimiter(1, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', false)

            const events = [
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'), // Will exceed limit
            ]

            const results = await step(events)

            expect(results).toHaveLength(2)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.REDIRECT)
                if (result.type === PipelineResultType.REDIRECT) {
                    expect(result.preserveKey).toBe(false)
                }
            })
        })
    })
})

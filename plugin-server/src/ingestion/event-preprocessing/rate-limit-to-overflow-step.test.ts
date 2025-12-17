import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { EventHeaders, PipelineEvent, Team } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { MemoryRateLimiter } from '../utils/overflow-detector'
import { RateLimitToOverflowStepInput, createRateLimitToOverflowStep } from './rate-limit-to-overflow-step'

const createMockEvent = (token: string, distinctId: string, now?: Date): RateLimitToOverflowStepInput => ({
    headers: {
        token,
        distinct_id: distinctId,
        now: now ?? new Date(),
        force_disable_person_processing: false,
        historical_migration: false,
    },
    eventWithTeam: {
        message: createTestMessage(),
        event: { distinct_id: distinctId, token } as PipelineEvent,
        team: { id: 1 } as Team,
        headers: {} as EventHeaders,
    },
})

describe('createRateLimitToOverflowStep', () => {
    describe('when overflow is disabled', () => {
        it('returns all events as ok', async () => {
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
        it('returns ok for events below rate limit', async () => {
            const rateLimiter = new MemoryRateLimiter(100, 10)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [createMockEvent('token1', 'user1'), createMockEvent('token1', 'user2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('redirects events that exceed rate limit', async () => {
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

        it('groups events by token:distinct_id key', async () => {
            const rateLimiter = new MemoryRateLimiter(3, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [
                // 3 events for token1:user1 (at limit)
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                // 3 events for token1:user2 (at limit)
                createMockEvent('token1', 'user2'),
                createMockEvent('token1', 'user2'),
                createMockEvent('token1', 'user2'),
                // 3 events for token2:user1 (at limit)
                createMockEvent('token2', 'user1'),
                createMockEvent('token2', 'user1'),
                createMockEvent('token2', 'user1'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(9)
            // All should be ok since each key has exactly 3 events (at the limit)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('redirects only keys that exceed limit, not others', async () => {
            const rateLimiter = new MemoryRateLimiter(4, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [
                // 5 events for token1:user1 (exceeds limit of 4)
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                // 2 events for token1:user2 (below limit)
                createMockEvent('token1', 'user2'),
                createMockEvent('token1', 'user2'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(7)

            // First 5 should be redirected (token1:user1 exceeded)
            for (let i = 0; i < 5; i++) {
                expect(results[i].type).toBe(PipelineResultType.REDIRECT)
            }

            // Last 2 should be ok (token1:user2 below limit)
            expect(results[5].type).toBe(PipelineResultType.OK)
            expect(results[6].type).toBe(PipelineResultType.OK)
        })

        it('handles empty token or distinct_id', async () => {
            const rateLimiter = new MemoryRateLimiter(5, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const events = [createMockEvent('', 'user1'), createMockEvent('token1', ''), createMockEvent('', '')]

            const results = await step(events)

            expect(results).toHaveLength(3)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('uses headers timestamp for rate limiting', async () => {
            const rateLimiter = new MemoryRateLimiter(2, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const baseTime = new Date()

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

        it('preserves input structure in results', async () => {
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

        it('maintains ordering of events in results', async () => {
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

            for (let i = 0; i < results.length; i++) {
                const result = results[i]
                if (result.type === PipelineResultType.OK) {
                    expect(result.value.headers.token).toBe(events[i].headers.token)
                    expect(result.value.headers.distinct_id).toBe(events[i].headers.distinct_id)
                }
            }
        })

        it('preserves partition key when preservePartitionLocality is true', async () => {
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

        it('does not preserve partition key when preservePartitionLocality is false', async () => {
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

        it('rate limiter state persists across step calls', async () => {
            const rateLimiter = new MemoryRateLimiter(5, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const baseTime = new Date()

            // First batch: consume 3 of 5 tokens
            const firstBatch = Array.from({ length: 3 }, () => createMockEvent('token1', 'user1', baseTime))
            const firstResults = await step(firstBatch)

            expect(firstResults).toHaveLength(3)
            firstResults.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })

            // Second batch: consume 3 more tokens (total 6, exceeds limit of 5)
            const secondBatch = Array.from({ length: 3 }, () => createMockEvent('token1', 'user1', baseTime))
            const secondResults = await step(secondBatch)

            expect(secondResults).toHaveLength(3)
            secondResults.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.REDIRECT)
            })
        })

        it('tokens replenish over time allowing more events', async () => {
            // Capacity 4, replenish 2 tokens per second
            const rateLimiter = new MemoryRateLimiter(4, 2)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const baseTime = new Date()

            // First batch at T=0: consume all 4 tokens
            const firstBatch = Array.from({ length: 4 }, () => createMockEvent('token1', 'user1', baseTime))
            const firstResults = await step(firstBatch)

            expect(firstResults).toHaveLength(4)
            firstResults.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })

            // Second batch at T=0: no tokens left, should redirect
            const secondBatch = [createMockEvent('token1', 'user1', baseTime)]
            const secondResults = await step(secondBatch)

            expect(secondResults).toHaveLength(1)
            expect(secondResults[0].type).toBe(PipelineResultType.REDIRECT)

            // Third batch at T=2s: replenished 4 tokens (2/sec * 2s = 4, capped at capacity)
            const laterTime = new Date(baseTime.getTime() + 2000)
            const thirdBatch = Array.from({ length: 3 }, () => createMockEvent('token1', 'user1', laterTime))
            const thirdResults = await step(thirdBatch)

            expect(thirdResults).toHaveLength(3)
            thirdResults.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('different keys have independent rate limit state across calls', async () => {
            const rateLimiter = new MemoryRateLimiter(3, 1)
            const step = createRateLimitToOverflowStep(rateLimiter, true, 'overflow_topic', true)

            const baseTime = new Date()

            // First batch: exhaust tokens for user1
            const firstBatch = Array.from({ length: 3 }, () => createMockEvent('token1', 'user1', baseTime))
            await step(firstBatch)

            // Second batch: user1 should be redirected, user2 should be ok
            const secondBatch = [
                createMockEvent('token1', 'user1', baseTime),
                createMockEvent('token1', 'user2', baseTime),
            ]
            const secondResults = await step(secondBatch)

            expect(secondResults).toHaveLength(2)
            expect(secondResults[0].type).toBe(PipelineResultType.REDIRECT)
            expect(secondResults[1].type).toBe(PipelineResultType.OK)
        })
    })
})

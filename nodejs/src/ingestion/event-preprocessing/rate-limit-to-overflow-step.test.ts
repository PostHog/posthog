import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { EventHeaders, PipelineEvent, Team } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
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

const createMockOverflowRedirectService = (
    keysToRedirect: Set<string> = new Set()
): jest.Mocked<OverflowRedirectService> => ({
    handleEventBatch: jest.fn().mockResolvedValue(keysToRedirect),
    healthCheck: jest.fn(),
    shutdown: jest.fn(),
})

describe('createRateLimitToOverflowStep', () => {
    describe('when service is not provided (overflow disabled)', () => {
        it('returns all events as ok', async () => {
            const step = createRateLimitToOverflowStep('overflow_topic', true, undefined)

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

    describe('when service is provided (overflow enabled)', () => {
        it('returns ok for events not flagged by service', async () => {
            const service = createMockOverflowRedirectService()
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const events = [createMockEvent('token1', 'user1'), createMockEvent('token1', 'user2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('redirects events flagged by service', async () => {
            const service = createMockOverflowRedirectService(new Set(['token1:user1']))
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const events = [createMockEvent('token1', 'user1'), createMockEvent('token1', 'user2')]

            const results = await step(events)

            expect(results).toHaveLength(2)
            expect(results[0].type).toBe(PipelineResultType.REDIRECT)
            if (results[0].type === PipelineResultType.REDIRECT) {
                expect(results[0].reason).toBe('rate_limit_exceeded')
                expect(results[0].topic).toBe('overflow_topic')
            }
            expect(results[1].type).toBe(PipelineResultType.OK)
        })

        it('redirects all events for flagged key', async () => {
            const service = createMockOverflowRedirectService(new Set(['token1:user1']))
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            // Create 10 events for the same flagged key
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

        it('calls service with correct batch format', async () => {
            const service = createMockOverflowRedirectService()
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const baseTime = new Date()
            const events = [
                createMockEvent('token1', 'user1', baseTime),
                createMockEvent('token1', 'user1', baseTime),
                createMockEvent('token2', 'user2', baseTime),
            ]

            await step(events)

            expect(service.handleEventBatch).toHaveBeenCalledWith('events', [
                { key: { token: 'token1', distinctId: 'user1' }, eventCount: 2, firstTimestamp: baseTime.getTime() },
                { key: { token: 'token2', distinctId: 'user2' }, eventCount: 1, firstTimestamp: baseTime.getTime() },
            ])
        })

        it('groups events by token:distinct_id key', async () => {
            const service = createMockOverflowRedirectService()
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const events = [
                // 3 events for token1:user1
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                // 3 events for token1:user2
                createMockEvent('token1', 'user2'),
                createMockEvent('token1', 'user2'),
                createMockEvent('token1', 'user2'),
                // 3 events for token2:user1
                createMockEvent('token2', 'user1'),
                createMockEvent('token2', 'user1'),
                createMockEvent('token2', 'user1'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(9)
            // All should be ok since service returns empty set
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })

            // Service should be called with 3 unique keys
            expect(service.handleEventBatch).toHaveBeenCalledTimes(1)
            const batches = (service.handleEventBatch as jest.Mock).mock.calls[0][1]
            expect(batches).toHaveLength(3)
        })

        it('redirects only keys flagged by service, not others', async () => {
            const service = createMockOverflowRedirectService(new Set(['token1:user1']))
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const events = [
                // 5 events for token1:user1 (flagged)
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                createMockEvent('token1', 'user1'),
                // 2 events for token1:user2 (not flagged)
                createMockEvent('token1', 'user2'),
                createMockEvent('token1', 'user2'),
            ]

            const results = await step(events)

            expect(results).toHaveLength(7)

            // First 5 should be redirected (token1:user1 flagged)
            for (let i = 0; i < 5; i++) {
                expect(results[i].type).toBe(PipelineResultType.REDIRECT)
            }

            // Last 2 should be ok (token1:user2 not flagged)
            expect(results[5].type).toBe(PipelineResultType.OK)
            expect(results[6].type).toBe(PipelineResultType.OK)
        })

        it('handles empty token or distinct_id', async () => {
            const service = createMockOverflowRedirectService()
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const events = [createMockEvent('', 'user1'), createMockEvent('token1', ''), createMockEvent('', '')]

            const results = await step(events)

            expect(results).toHaveLength(3)
            results.forEach((result) => {
                expect(result.type).toBe(PipelineResultType.OK)
            })
        })

        it('preserves input structure in results', async () => {
            const service = createMockOverflowRedirectService()
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

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
            const service = createMockOverflowRedirectService()
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

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
            const service = createMockOverflowRedirectService(new Set(['token1:user1']))
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const events = [createMockEvent('token1', 'user1')]

            const results = await step(events)

            expect(results).toHaveLength(1)
            expect(results[0].type).toBe(PipelineResultType.REDIRECT)
            if (results[0].type === PipelineResultType.REDIRECT) {
                expect(results[0].preserveKey).toBe(true)
            }
        })

        it('does not preserve partition key when preservePartitionLocality is false', async () => {
            const service = createMockOverflowRedirectService(new Set(['token1:user1']))
            const step = createRateLimitToOverflowStep('overflow_topic', false, service)

            const events = [createMockEvent('token1', 'user1')]

            const results = await step(events)

            expect(results).toHaveLength(1)
            expect(results[0].type).toBe(PipelineResultType.REDIRECT)
            if (results[0].type === PipelineResultType.REDIRECT) {
                expect(results[0].preserveKey).toBe(false)
            }
        })

        it('handles distinct_id with colons correctly', async () => {
            const service = createMockOverflowRedirectService(new Set(['token1:user:with:colons']))
            const step = createRateLimitToOverflowStep('overflow_topic', true, service)

            const events = [createMockEvent('token1', 'user:with:colons')]

            const results = await step(events)

            expect(results).toHaveLength(1)
            expect(results[0].type).toBe(PipelineResultType.REDIRECT)
        })
    })
})

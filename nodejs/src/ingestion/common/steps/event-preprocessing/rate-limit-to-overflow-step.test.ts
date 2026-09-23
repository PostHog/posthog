import { OVERFLOW_OUTPUT } from '~/common/outputs'
import { COOKIELESS_SENTINEL_VALUE } from '~/ingestion/common/cookieless/cookieless-manager'
import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { PipelineResultType } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { RateLimitToOverflowStepInput, createRateLimitToOverflowStep } from './rate-limit-to-overflow-step'

// Mirrors capture: the message key is `token:distinct_id` for regular events and
// `token:client_ip` for cookieless events; spread events have no key.
const createMockEvent = (
    token: string,
    distinctId: string,
    options: { kafkaKeySuffix?: string | null; now?: Date } = {}
): RateLimitToOverflowStepInput => {
    const suffix = options.kafkaKeySuffix === undefined ? distinctId : options.kafkaKeySuffix
    return {
        message: { key: suffix === null ? null : Buffer.from(`${token}:${suffix}`) },
        headers: createTestEventHeaders({ token, distinct_id: distinctId, now: options.now ?? new Date() }),
    }
}

const createMockOverflowRedirectService = (
    keysToRedirect: Set<string> = new Set()
): jest.Mocked<OverflowRedirectService> => ({
    handleEventBatch: jest.fn().mockResolvedValue(keysToRedirect),
    healthCheck: jest.fn(),
    shutdown: jest.fn(),
})

describe('createRateLimitToOverflowStep', () => {
    it('returns all events as ok when service is not provided (overflow disabled)', async () => {
        const step = createRateLimitToOverflowStep(true, undefined)

        const events = [createMockEvent('token1', 'user1'), createMockEvent('token2', 'user2')]

        const results = await step(events)

        expect(results).toHaveLength(2)
        results.forEach((result) => {
            expect(result.type).toBe(PipelineResultType.OK)
        })
    })

    it('calls service with events grouped by the message key split on the token prefix', async () => {
        const service = createMockOverflowRedirectService()
        const step = createRateLimitToOverflowStep(true, service)

        const baseTime = new Date()
        const events = [
            createMockEvent('token1', 'user1', { now: baseTime }),
            createMockEvent('token1', 'user1', { now: baseTime }),
            createMockEvent('token2', 'user2', { now: baseTime }),
        ]

        await step(events)

        expect(service.handleEventBatch).toHaveBeenCalledWith([
            {
                key: 'token1:user1',
                headersPerEvent: [events[0].headers, events[1].headers],
                firstTimestamp: baseTime.getTime(),
            },
            {
                key: 'token2:user2',
                headersPerEvent: [events[2].headers],
                firstTimestamp: baseTime.getTime(),
            },
        ])
    })

    it('redirects events for flagged keys and passes the rest, preserving order', async () => {
        const service = createMockOverflowRedirectService(new Set(['token1:user1']))
        const step = createRateLimitToOverflowStep(true, service)

        const events = [
            createMockEvent('token1', 'user1'),
            createMockEvent('token1', 'user2'),
            createMockEvent('token1', 'user1'),
        ]

        const results = await step(events)

        expect(results).toHaveLength(3)
        expect(results[0].type).toBe(PipelineResultType.REDIRECT)
        if (results[0].type === PipelineResultType.REDIRECT) {
            expect(results[0].reason).toBe('rate_limit_exceeded')
            expect(results[0].output).toBe(OVERFLOW_OUTPUT)
        }
        expect(results[1].type).toBe(PipelineResultType.OK)
        if (results[1].type === PipelineResultType.OK) {
            expect(results[1].value).toBe(events[1])
        }
        expect(results[2].type).toBe(PipelineResultType.REDIRECT)
    })

    it('uses the message key verbatim, including colons in the distinct id', async () => {
        const service = createMockOverflowRedirectService(new Set(['token1:user:with:colons']))
        const step = createRateLimitToOverflowStep(true, service)

        const results = await step([createMockEvent('token1', 'user:with:colons')])

        expect(results[0].type).toBe(PipelineResultType.REDIRECT)
        const batches = (service.handleEventBatch as jest.Mock).mock.calls[0][0]
        expect(batches[0].key).toBe('token1:user:with:colons')
    })

    it('aggregates cookieless events by client IP from the message key, not the hashed distinct_id', async () => {
        // Capture keys a cookieless event on token:client_ip while the header stays
        // the sentinel. One IP's stream must share a bucket even though every event
        // gets a fresh hashed distinct_id later, so a flag on the IP key redirects
        // all of that IP's events.
        const service = createMockOverflowRedirectService(new Set(['token1:1.2.3.4']))
        const step = createRateLimitToOverflowStep(true, service)

        const events = [
            createMockEvent('token1', COOKIELESS_SENTINEL_VALUE, { kafkaKeySuffix: '1.2.3.4' }),
            createMockEvent('token1', COOKIELESS_SENTINEL_VALUE, { kafkaKeySuffix: '1.2.3.4' }),
            createMockEvent('token1', COOKIELESS_SENTINEL_VALUE, { kafkaKeySuffix: '5.6.7.8' }),
        ]

        const results = await step(events)

        const batches = (service.handleEventBatch as jest.Mock).mock.calls[0][0]
        expect(batches).toHaveLength(2)
        expect(batches[0].key).toBe('token1:1.2.3.4')
        expect(batches[0].headersPerEvent).toHaveLength(2)

        expect(results[0].type).toBe(PipelineResultType.REDIRECT)
        expect(results[1].type).toBe(PipelineResultType.REDIRECT)
        expect(results[2].type).toBe(PipelineResultType.OK)
    })

    it('falls back to token:distinct_id from headers for events without a message key', async () => {
        const service = createMockOverflowRedirectService(new Set(['token1:user1']))
        const step = createRateLimitToOverflowStep(true, service)

        const events = [createMockEvent('token1', 'user1', { kafkaKeySuffix: null })]

        const results = await step(events)

        expect(results[0].type).toBe(PipelineResultType.REDIRECT)
        const batches = (service.handleEventBatch as jest.Mock).mock.calls[0][0]
        expect(batches[0].key).toBe('token1:user1')
    })

    it.each([
        [true, true],
        [false, false],
    ])('propagates preservePartitionLocality=%s to the redirect result', async (locality, expected) => {
        const service = createMockOverflowRedirectService(new Set(['token1:user1']))
        const step = createRateLimitToOverflowStep(locality, service)

        const results = await step([createMockEvent('token1', 'user1')])

        expect(results[0].type).toBe(PipelineResultType.REDIRECT)
        if (results[0].type === PipelineResultType.REDIRECT) {
            expect(results[0].preserveKey).toBe(expected)
        }
    })
})

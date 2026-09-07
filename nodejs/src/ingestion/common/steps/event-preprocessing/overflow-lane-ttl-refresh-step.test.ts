import { OverflowRedirectService } from '~/ingestion/common/overflow-redirect/overflow-redirect-service'
import { PipelineResultType } from '~/ingestion/framework/results'
import { createTestEventHeaders } from '~/tests/helpers/event-headers'

import { OverflowLaneTTLRefreshStepInput, createOverflowLaneTTLRefreshStep } from './overflow-lane-ttl-refresh-step'

const createMockEvent = (
    token: string,
    distinctId: string,
    options: { kafkaKey?: string | null; now?: Date } = {}
): OverflowLaneTTLRefreshStepInput => ({
    message: {
        key: options.kafkaKey === null || options.kafkaKey === undefined ? null : Buffer.from(options.kafkaKey),
    },
    headers: createTestEventHeaders({ token, distinct_id: distinctId, now: options.now ?? new Date() }),
})

const createMockService = (): jest.Mocked<OverflowRedirectService> => ({
    handleEventBatch: jest.fn().mockResolvedValue(new Set()),
    healthCheck: jest.fn(),
    shutdown: jest.fn(),
})

describe('createOverflowLaneTTLRefreshStep', () => {
    it('returns all events as ok with TTL refresh as side effect', async () => {
        const service = createMockService()
        const step = createOverflowLaneTTLRefreshStep(service)

        const events = [createMockEvent('token1', 'user1'), createMockEvent('token1', 'user2')]

        const results = await step(events)

        expect(results).toHaveLength(2)
        results.forEach((result) => {
            expect(result.type).toBe(PipelineResultType.OK)
            expect(result.sideEffects.length).toBe(1)
        })
    })

    it('refreshes the message key, the redirect-original-key header, or the headers fallback', async () => {
        const service = createMockService()
        const step = createOverflowLaneTTLRefreshStep(service)

        const baseTime = new Date()
        const events = [
            // Redirect with partition locality: the cookieless IP key survives.
            createMockEvent('token1', '$posthog_cookieless', { kafkaKey: 'token1:1.2.3.4', now: baseTime }),
            // Redirect without locality nulls the key but stamps the original into a header.
            {
                message: { key: null },
                headers: createTestEventHeaders({
                    token: 'token1',
                    distinct_id: '$posthog_cookieless',
                    redirect_original_key: 'token1:5.6.7.8',
                    now: baseTime,
                }),
            },
            // Routed to overflow at capture (no redirect): fall back to token:headers.distinct_id.
            createMockEvent('token1', 'user1', { kafkaKey: null, now: baseTime }),
            createMockEvent('token1', 'user1', { kafkaKey: null, now: baseTime }), // Duplicate key
        ]

        await step(events)

        expect(service.handleEventBatch).toHaveBeenCalledWith([
            {
                key: 'token1:1.2.3.4',
                headersPerEvent: [events[0].headers],
                firstTimestamp: baseTime.getTime(),
            },
            {
                key: 'token1:5.6.7.8',
                headersPerEvent: [events[1].headers],
                firstTimestamp: baseTime.getTime(),
            },
            {
                key: 'token1:user1',
                headersPerEvent: [events[2].headers, events[3].headers],
                firstTimestamp: baseTime.getTime(),
            },
        ])
    })

    it('handles empty batch', async () => {
        const service = createMockService()
        const step = createOverflowLaneTTLRefreshStep(service)

        const results = await step([])

        expect(results).toHaveLength(0)
        expect(service.handleEventBatch).not.toHaveBeenCalled()
    })
})

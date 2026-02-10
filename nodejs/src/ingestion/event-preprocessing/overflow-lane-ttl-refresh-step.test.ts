import { PluginEvent } from '@posthog/plugin-scaffold'

import { PipelineResultType } from '../pipelines/results'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { createOverflowLaneTTLRefreshStep } from './overflow-lane-ttl-refresh-step'
import { OverflowLaneTTLRefreshStepInput } from './overflow-lane-ttl-refresh-step'

const createMockEvent = (token: string, distinctId: string, now?: Date): OverflowLaneTTLRefreshStepInput => ({
    headers: {
        token,
        distinct_id: distinctId,
        now: now ?? new Date(),
        force_disable_person_processing: false,
        historical_migration: false,
    },
    event: {
        distinct_id: distinctId,
        team_id: 1,
        ip: '127.0.0.1',
        site_url: 'https://example.com',
        now: (now ?? new Date()).toISOString(),
        event: 'test-event',
        uuid: '123e4567-e89b-12d3-a456-426614174000',
    } as PluginEvent,
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

    it('calls service with deduplicated keys', async () => {
        const service = createMockService()
        const step = createOverflowLaneTTLRefreshStep(service)

        const baseTime = new Date()
        const events = [
            createMockEvent('token1', 'user1', baseTime),
            createMockEvent('token1', 'user1', baseTime), // Duplicate key
            createMockEvent('token1', 'user2', baseTime),
        ]

        await step(events)

        expect(service.handleEventBatch).toHaveBeenCalledWith('events', [
            { key: { token: 'token1', distinctId: 'user1' }, eventCount: 2, firstTimestamp: baseTime.getTime() },
            { key: { token: 'token1', distinctId: 'user2' }, eventCount: 1, firstTimestamp: baseTime.getTime() },
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

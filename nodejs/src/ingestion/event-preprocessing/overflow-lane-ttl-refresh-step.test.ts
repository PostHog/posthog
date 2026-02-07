import { createTestMessage } from '../../../tests/helpers/kafka-message'
import { EventHeaders, PipelineEvent, Team } from '../../types'
import { PipelineResultType } from '../pipelines/results'
import { OverflowRedirectService } from '../utils/overflow-redirect/overflow-redirect-service'
import { createOverflowLaneTTLRefreshStep } from './overflow-lane-ttl-refresh-step'
import { RateLimitToOverflowStepInput } from './rate-limit-to-overflow-step'

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

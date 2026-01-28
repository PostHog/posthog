import { HealthCheckResultError, HealthCheckResultOk } from '../../../types'
import { OverflowLaneOverflowRedirect } from './overflow-lane-overflow-redirect'
import { OverflowEventBatch } from './overflow-redirect-service'
import { OverflowRedisRepository } from './overflow-redis-repository'

const createMockRepository = (): jest.Mocked<OverflowRedisRepository> => ({
    batchCheck: jest.fn().mockResolvedValue(new Map()),
    batchFlag: jest.fn().mockResolvedValue(undefined),
    batchRefreshTTL: jest.fn().mockResolvedValue(undefined),
    healthCheck: jest.fn().mockResolvedValue(new HealthCheckResultOk()),
})

const createBatch = (
    token: string,
    distinctId: string,
    eventCount: number = 1,
    firstTimestamp: number = Date.now()
): OverflowEventBatch => ({
    key: { token, distinctId },
    eventCount,
    firstTimestamp,
})

describe('OverflowLaneOverflowRedirect', () => {
    let mockRepository: jest.Mocked<OverflowRedisRepository>
    let service: OverflowLaneOverflowRedirect

    beforeEach(() => {
        mockRepository = createMockRepository()
        service = new OverflowLaneOverflowRedirect({
            redisRepository: mockRepository,
        })
    })

    describe('handleEventBatch', () => {
        it('always returns empty set (no redirects from overflow lane)', async () => {
            const batch = [createBatch('token1', 'user1', 100), createBatch('token1', 'user2', 100)]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(0)
        })

        it('refreshes TTL for all keys in batch', async () => {
            const batch = [createBatch('token1', 'user1'), createBatch('token1', 'user2')]

            await service.handleEventBatch('events', batch)

            expect(mockRepository.batchRefreshTTL).toHaveBeenCalledWith('events', [
                { token: 'token1', distinctId: 'user1' },
                { token: 'token1', distinctId: 'user2' },
            ])
        })

        it('uses correct overflow type', async () => {
            await service.handleEventBatch('recordings', [createBatch('token1', 'session1')])

            expect(mockRepository.batchRefreshTTL).toHaveBeenCalledWith('recordings', [
                { token: 'token1', distinctId: 'session1' },
            ])
        })

        it('handles empty batch gracefully', async () => {
            const result = await service.handleEventBatch('events', [])

            expect(result.size).toBe(0)
            expect(mockRepository.batchRefreshTTL).not.toHaveBeenCalled()
        })

        it('sends all keys in a single batchRefreshTTL call', async () => {
            const batch = [
                createBatch('token1', 'user1'),
                createBatch('token1', 'user2'),
                createBatch('token2', 'user1'),
            ]

            await service.handleEventBatch('events', batch)

            expect(mockRepository.batchRefreshTTL).toHaveBeenCalledTimes(1)
            expect(mockRepository.batchRefreshTTL).toHaveBeenCalledWith('events', [
                { token: 'token1', distinctId: 'user1' },
                { token: 'token1', distinctId: 'user2' },
                { token: 'token2', distinctId: 'user1' },
            ])
        })
    })

    describe('fail-open behavior', () => {
        it('returns empty set even when batchRefreshTTL is a no-op', async () => {
            // The repository layer handles Redis errors internally (fail-open)
            // From the service perspective, batchRefreshTTL completes without error
            // and the service still returns an empty set (no redirects from overflow lane)
            const batch = [createBatch('token1', 'user1')]

            const result = await service.handleEventBatch('events', batch)

            expect(result.size).toBe(0)
        })
    })

    describe('healthCheck', () => {
        it('delegates to repository', async () => {
            const result = await service.healthCheck()

            expect(result.status).toBe('ok')
            expect(mockRepository.healthCheck).toHaveBeenCalled()
        })

        it('returns error when repository health check fails', async () => {
            mockRepository.healthCheck.mockResolvedValue(
                new HealthCheckResultError('OverflowRedirectService is down', {})
            )

            const result = await service.healthCheck()

            expect(result.status).toBe('error')
        })
    })

    describe('shutdown', () => {
        it('completes without error', async () => {
            await expect(service.shutdown()).resolves.toBeUndefined()
        })
    })
})

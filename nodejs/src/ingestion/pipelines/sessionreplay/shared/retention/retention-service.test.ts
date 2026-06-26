import { Redis } from 'ioredis'

import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { RedisPool, TeamId } from '~/types'

import { RetentionServiceMetrics } from './metrics'
import { RetentionService } from './retention-service'

jest.mock('./metrics', () => ({
    RetentionServiceMetrics: {
        incrementLookupErrors: jest.fn(),
    },
}))

jest.mock('~/ingestion/pipelines/sessionreplay/sessions/metrics', () => ({
    SessionBatchMetrics: {
        observeRetentionRedisLatency: jest.fn(),
        incrementRetentionRedisFallbacks: jest.fn(),
    },
}))

jest.mock('~/common/utils/logger', () => ({
    logger: {
        warn: jest.fn(),
    },
}))

describe('RetentionService', () => {
    let retentionService: RetentionService
    let mockRedisClient: jest.Mocked<Redis>
    let mockTeamService: jest.Mocked<TeamService>

    beforeEach(() => {
        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            set: jest.fn().mockResolvedValue('OK'),
        } as unknown as jest.Mocked<Redis>

        const mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn(),
        } as unknown as jest.Mocked<RedisPool>

        mockTeamService = {
            getRetentionPeriodByTeamId: jest.fn().mockImplementation((teamId: TeamId) => {
                return {
                    1: '30d', // Valid
                    2: '1y', // Valid
                    3: null, // Missing
                    4: 'foobar', //Invalid
                }[teamId]
            }),
        } as unknown as jest.Mocked<TeamService>

        retentionService = new RetentionService(mockRedisPool, mockTeamService)
    })

    describe('getRetentionByTeamId', () => {
        it('should return retention period for valid team id 1', async () => {
            const retentionPeriod = await retentionService.getRetentionByTeamId(1)
            expect(retentionPeriod).toEqual('30d')
        })

        it('should return retention period for valid team id 2', async () => {
            const retentionPeriod = await retentionService.getRetentionByTeamId(2)
            expect(retentionPeriod).toEqual('1y')
        })

        it('should throw error for unknown team id', async () => {
            const retentionPromise = retentionService.getRetentionByTeamId(3)
            await expect(retentionPromise).rejects.toThrow('Error during retention period lookup: Unknown team id 3')
        })

        it('should throw error for invalid retention period', async () => {
            const retentionPromise = retentionService.getRetentionByTeamId(4)
            await expect(retentionPromise).rejects.toThrow(
                'Error during retention period lookup: Got invalid value foobar'
            )
        })
    })

    describe('getSessionRetention', () => {
        it('should return retention period from Redis if cached', async () => {
            mockRedisClient.get.mockResolvedValue('30d')

            const retentionPeriod = await retentionService.getSessionRetention(1, '123')
            expect(retentionPeriod).toEqual('30d')
            expect(mockRedisClient.get).toHaveBeenCalledWith('@posthog/replay/session-retention-123')
        })

        it('should fall back to team service and cache in Redis when not in Redis', async () => {
            mockRedisClient.get.mockResolvedValue(null)

            const retentionPeriod = await retentionService.getSessionRetention(1, '123')
            expect(retentionPeriod).toEqual('30d')
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(1)

            // Wait for fire-and-forget Redis SET
            await new Promise((resolve) => setImmediate(resolve))
            expect(mockRedisClient.set).toHaveBeenCalledWith(
                '@posthog/replay/session-retention-123',
                '30d',
                'EX',
                24 * 60 * 60
            )
        })

        it('should fall back to team service on Redis error', async () => {
            mockRedisClient.get.mockRejectedValue(new Error('Redis connection failed'))

            const retentionPeriod = await retentionService.getSessionRetention(1, '123')
            expect(retentionPeriod).toEqual('30d')
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(1)
        })

        it('should throw error for unknown team id', async () => {
            const retentionPromise = retentionService.getSessionRetention(3, '456')
            await expect(retentionPromise).rejects.toThrow('Error during retention period lookup: Unknown team id 3')
        })

        it('should throw error for invalid retention period', async () => {
            const retentionPromise = retentionService.getSessionRetention(4, '654')
            await expect(retentionPromise).rejects.toThrow(
                'Error during retention period lookup: Got invalid value foobar'
            )
        })
    })

    describe('getSessionRetentionDays', () => {
        it('should return 30 for 30d retention', async () => {
            const days = await retentionService.getSessionRetentionDays(1, '123')
            expect(days).toEqual(30)
        })

        it('should return 365 for 1y retention', async () => {
            mockRedisClient.get.mockResolvedValue('1y')
            const days = await retentionService.getSessionRetentionDays(2, '321')
            expect(days).toEqual(365)
        })
    })

    describe('metrics', () => {
        it('should increment lookup errors for unknown team id', async () => {
            const retentionPromise = retentionService.getSessionRetention(3, '456')
            await expect(retentionPromise).rejects.toThrow('Error during retention period lookup: Unknown team id 3')
            expect(RetentionServiceMetrics.incrementLookupErrors).toHaveBeenCalledTimes(1)
        })

        it('should increment lookup errors for invalid retention period', async () => {
            const retentionPromise = retentionService.getSessionRetention(4, '654')
            await expect(retentionPromise).rejects.toThrow(
                'Error during retention period lookup: Got invalid value foobar'
            )
            expect(RetentionServiceMetrics.incrementLookupErrors).toHaveBeenCalledTimes(1)
        })
    })
})

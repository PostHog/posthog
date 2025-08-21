import { Redis } from 'ioredis'

import { RedisPool, TeamId } from '../../../../types'
import { TeamService } from '../teams/team-service'
import { RetentionService } from './retention-service'

jest.mock('./metrics', () => ({
    RetentionServiceMetrics: {
        incrementRefreshErrors: jest.fn(),
        incrementRefreshCount: jest.fn(),
        incrementLookupErrors: jest.fn(),
    },
}))

describe('RetentionService', () => {
    let retentionService: RetentionService
    let mockRedisClient: jest.Mocked<Redis>

    beforeEach(() => {
        jest.useFakeTimers()

        mockRedisClient = {
            get: jest.fn().mockResolvedValue(null),
            set: jest.fn(),
        } as unknown as jest.Mocked<Redis>

        const mockRedisPool = {
            acquire: jest.fn().mockReturnValue(mockRedisClient),
            release: jest.fn(),
        } as unknown as jest.Mocked<RedisPool>

        const mockTeamService = {
            getRetentionPeriodByTeamId: jest.fn().mockImplementation((teamId: TeamId) => {
                return {
                    1: '30d',
                    2: '1y',
                    3: null,
                }[teamId]
            }),
        } as unknown as jest.Mocked<TeamService>

        retentionService = new RetentionService(mockRedisPool, mockTeamService)
    })

    afterEach(() => {
        jest.useRealTimers()
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
    })

    describe('getSessionRetention', () => {
        it('should return retention period for valid team id 1', async () => {
            const retentionPeriod = await retentionService.getSessionRetention(1, '123')
            expect(retentionPeriod).toEqual('30d')
        })

        it('should return retention period for valid team id 2', async () => {
            const retentionPeriod = await retentionService.getSessionRetention(2, '321')
            expect(retentionPeriod).toEqual('1y')
        })

        it('should throw error for unknown team id', async () => {
            const retentionPromise = retentionService.getSessionRetention(3, '456')
            await expect(retentionPromise).rejects.toThrow('Error during retention period lookup: Unknown team id 3')
        })

        it('should load retention from Redis if key exists', async () => {
            mockRedisClient.get = jest.fn().mockReturnValue('30d')

            const retentionPeriod = await retentionService.getSessionRetention(1, '123')
            expect(retentionPeriod).toEqual('30d')

            expect(mockRedisClient.get).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.get).toHaveBeenCalledWith('@posthog/replay/session-retention-123')
        })

        it('should store retention in Redis if key does not exist', async () => {
            mockRedisClient.get = jest.fn().mockReturnValue(null)

            const retentionPeriod = await retentionService.getSessionRetention(1, '123')
            expect(retentionPeriod).toEqual('30d')

            expect(mockRedisClient.set).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.set).toHaveBeenCalledWith(
                '@posthog/replay/session-retention-123',
                '30d',
                'EX',
                24 * 60 * 60
            )
        })
    })
})

import { Redis } from 'ioredis'
import { DateTime } from 'luxon'

import { RedisPool, TeamId } from '~/types'

import { PostgresRouter } from '../../../../utils/db/postgres'
import { MessageWithTeam } from '../teams/types'
import { RetentionPeriod } from '../types'
import { RetentionService } from './retention-service'
import { MessageWithRetention } from './types'

const createTeamMessage = (teamId: TeamId): MessageWithTeam => ({
    team: {
        teamId: teamId,
        consoleLogIngestionEnabled: true,
    },
    data: {
        metadata: {
            partition: 0,
            topic: 'test',
            offset: 0,
            timestamp: Date.now(),
            rawSize: 100,
        },
        headers: undefined,
        distinct_id: 'distinct_id',
        session_id: 'session_id',
        eventsByWindowId: {},
        eventsRange: {
            start: DateTime.fromMillis(0),
            end: DateTime.fromMillis(0),
        },
        snapshot_source: null,
        snapshot_library: null,
    },
})

const createRetentionMessage = (teamId: TeamId, retentionPeriod: RetentionPeriod): MessageWithRetention => ({
    retentionPeriod: retentionPeriod,
    team: {
        teamId: teamId,
        consoleLogIngestionEnabled: true,
    },
    data: {
        metadata: {
            partition: 0,
            topic: 'test',
            offset: 0,
            timestamp: Date.now(),
            rawSize: 100,
        },
        headers: undefined,
        distinct_id: 'distinct_id',
        session_id: 'session_id',
        eventsByWindowId: {},
        eventsRange: {
            start: DateTime.fromMillis(0),
            end: DateTime.fromMillis(0),
        },
        snapshot_source: null,
        snapshot_library: null,
    },
})

describe('RetentionService', () => {
    let retentionService: RetentionService
    let fetchSpy: jest.SpyInstance
    let mockRedisClient: jest.Mocked<Redis>

    beforeEach(() => {
        jest.useFakeTimers()
        const mockPostgres = {} as jest.Mocked<PostgresRouter>

        mockRedisClient = {
            exists: jest.fn(),
            get: jest.fn(),
            set: jest.fn(),
            expire: jest.fn(),
        } as unknown as jest.Mocked<Redis>

        const mockRedisPool = {
            acquire: jest.fn().mockReturnValue(mockRedisClient),
            release: jest.fn(),
        } as unknown as jest.Mocked<RedisPool>

        retentionService = new RetentionService(mockPostgres, mockRedisPool)

        fetchSpy = jest.spyOn(retentionService as any, 'fetchTeamRetentionPeriods').mockResolvedValue({
            1: '30d',
            2: '1y',
        })
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

        it('should cache results and not fetch again within refresh period', async () => {
            await retentionService.getRetentionByTeamId(1)
            await retentionService.getRetentionByTeamId(2)

            // Advance time but not enough to trigger refresh
            jest.advanceTimersByTime(4 * 60 * 1000) // 4 minutes (refresh is 5 minutes)

            await retentionService.getRetentionByTeamId(1)
            await retentionService.getRetentionByTeamId(2)

            expect(fetchSpy).toHaveBeenCalledTimes(1)
        })

        it('should refresh after max age', async () => {
            await retentionService.getRetentionByTeamId(1)
            expect(fetchSpy).toHaveBeenCalledTimes(1)

            // Move time forward past the refresh interval
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // This should trigger a refresh
            await retentionService.getRetentionByTeamId(1)
            expect(fetchSpy).toHaveBeenCalledTimes(2)
        })

        it('should handle refresh errors and return cached data', async () => {
            // First call succeeds
            await retentionService.getRetentionByTeamId(1)
            expect(fetchSpy).toHaveBeenCalledTimes(1)

            // Make next refresh fail
            fetchSpy.mockRejectedValueOnce(new Error('Refresh failed'))

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // Should still return cached data
            const retentionPeriod = await retentionService.getRetentionByTeamId(1)
            expect(retentionPeriod).toEqual('30d')
        })

        it('should eventually update cache after successful refresh', async () => {
            // Initial fetch
            const retentionPeriod1 = await retentionService.getRetentionByTeamId(1)
            expect(retentionPeriod1).toEqual('30d')

            // Update mock data and capture the promise
            const mockFetchPromise = Promise.resolve({
                1: '90d',
            })
            fetchSpy.mockReturnValue(mockFetchPromise)

            // Fetch again, no changes expected due to cache
            const retentionPeriod2 = await retentionService.getRetentionByTeamId(1)
            expect(retentionPeriod2).toEqual('30d')

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // Wait for the new value to appear using a spinlock, don't advance time though
            while ((await retentionService.getRetentionByTeamId(1)) !== '90d') {
                await Promise.resolve() // Allow other promises to resolve
            }

            const retentionPeriod3 = await retentionService.getRetentionByTeamId(1)
            expect(retentionPeriod3).toEqual('90d')
        })

        it('should eventually return null when team is removed after refresh', async () => {
            // Initial fetch
            const retentionPeriod1 = await retentionService.getRetentionByTeamId(1)
            expect(retentionPeriod1).toEqual('30d')

            // Update mock data to remove the team
            const mockFetchPromise = Promise.resolve({
                2: '1y', // Remove team id 1
            })
            fetchSpy.mockReturnValue(mockFetchPromise)

            // Fetch again, no changes expected due to cache
            const retentionPeriod2 = await retentionService.getRetentionByTeamId(1)
            expect(retentionPeriod2).toEqual('30d')

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            try {
                // Wait for the new value to appear using a spinlock, don't advance time though
                while (true) {
                    await retentionService.getRetentionByTeamId(1)
                    await Promise.resolve() // Allow other promises to resolve
                }
            } catch (error) {
                expect(error.message).toMatch('Error during retention period lookup: Unknown team id 1')
            }
        })
    })

    describe('addRetentionToMessage', () => {
        it('should return retention period for valid team id 1', async () => {
            const validMessage = createTeamMessage(1)
            const messageWithRetention = await retentionService.addRetentionToMessage(validMessage)
            expect(messageWithRetention).toEqual(createRetentionMessage(1, '30d'))
        })

        it('should return retention period for valid team id 2', async () => {
            const validMessage = createTeamMessage(2)
            const messageWithRetention = await retentionService.addRetentionToMessage(validMessage)
            expect(messageWithRetention).toEqual(createRetentionMessage(2, '1y'))
        })

        it('should throw error for unknown team id', async () => {
            const invalidMessage = createTeamMessage(3)
            const messagePromise = retentionService.addRetentionToMessage(invalidMessage)
            await expect(messagePromise).rejects.toThrow('Error during retention period lookup: Unknown team id 3')
        })

        it('should cache results and not fetch again within refresh period', async () => {
            await retentionService.addRetentionToMessage(createTeamMessage(1))
            await retentionService.addRetentionToMessage(createTeamMessage(2))

            // Advance time but not enough to trigger refresh
            jest.advanceTimersByTime(4 * 60 * 1000) // 4 minutes (refresh is 5 minutes)

            await retentionService.addRetentionToMessage(createTeamMessage(1))
            await retentionService.addRetentionToMessage(createTeamMessage(2))

            expect(fetchSpy).toHaveBeenCalledTimes(1)
        })

        it('should refresh after max age', async () => {
            await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(fetchSpy).toHaveBeenCalledTimes(1)

            // Move time forward past the refresh interval
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // This should trigger a refresh
            await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(fetchSpy).toHaveBeenCalledTimes(2)
        })

        it('should handle refresh errors and return cached data', async () => {
            // First call succeeds
            await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(fetchSpy).toHaveBeenCalledTimes(1)

            // Make next refresh fail
            fetchSpy.mockRejectedValueOnce(new Error('Refresh failed'))

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // Should still return cached data
            const messageWithRetention = await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(messageWithRetention).toEqual(createRetentionMessage(1, '30d'))
        })

        it('should eventually update cache after successful refresh', async () => {
            // Initial fetch
            const messageWithRetention1 = await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(messageWithRetention1).toEqual(createRetentionMessage(1, '30d'))

            // Update mock data and capture the promise
            const mockFetchPromise = Promise.resolve({
                1: '90d',
            })
            fetchSpy.mockReturnValue(mockFetchPromise)

            // Fetch again, no changes expected due to cache
            const messageWithRetention2 = await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(messageWithRetention2).toEqual(createRetentionMessage(1, '30d'))

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            // Wait for the new value to appear using a spinlock, don't advance time though (use getRetentionByTeamId here for easier comparison)
            while ((await retentionService.getRetentionByTeamId(1)) !== '90d') {
                await Promise.resolve() // Allow other promises to resolve
            }

            const messageWithRetention3 = await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(messageWithRetention3).toEqual(createRetentionMessage(1, '90d'))
        })

        it('should eventually throw error when team is removed after refresh', async () => {
            // Initial fetch
            const messageWithRetention1 = await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(messageWithRetention1).toEqual(createRetentionMessage(1, '30d'))

            // Update mock data and capture the promise
            const mockFetchPromise = Promise.resolve({
                2: '1y', // Remove team id 1
            })
            fetchSpy.mockReturnValue(mockFetchPromise)

            // Fetch again, no changes expected due to cache
            const messageWithRetention2 = await retentionService.addRetentionToMessage(createTeamMessage(1))
            expect(messageWithRetention2).toEqual(createRetentionMessage(1, '30d'))

            // Advance time to trigger refresh
            jest.advanceTimersByTime(5 * 60 * 1000 + 1)

            try {
                // Wait for the new value to appear using a spinlock, don't advance time though
                while (true) {
                    await retentionService.addRetentionToMessage(createTeamMessage(1))
                    await Promise.resolve() // Allow other promises to resolve
                }
            } catch (error) {
                expect(error.message).toMatch('Error during retention period lookup: Unknown team id 1')
            }
        })

        it('should load retention from Redis if key exists', async () => {
            mockRedisClient.exists.mockReturnValue(1)
            mockRedisClient.get.mockReturnValue('30d')

            const validMessage = createTeamMessage(1)
            const messageWithRetention = await retentionService.addRetentionToMessage(validMessage)
            expect(messageWithRetention).toEqual(createRetentionMessage(1, '30d'))

            expect(mockRedisClient.exists).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.exists).toHaveBeenCalledWith('@posthog/replay/session-retention-session_id')
            expect(mockRedisClient.get).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.get).toHaveBeenCalledWith('@posthog/replay/session-retention-session_id')
        })

        it('should store retention in Redis if key does not exist', async () => {
            mockRedisClient.exists.mockReturnValue(0)

            const validMessage = createTeamMessage(1)
            const messageWithRetention = await retentionService.addRetentionToMessage(validMessage)
            expect(messageWithRetention).toEqual(createRetentionMessage(1, '30d'))

            expect(mockRedisClient.set).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.set).toHaveBeenCalledWith('@posthog/replay/session-retention-session_id', '30d')

            expect(mockRedisClient.expire).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.expire).toHaveBeenCalledWith(
                '@posthog/replay/session-retention-session_id',
                24 * 60 * 60
            )
        })
    })
})

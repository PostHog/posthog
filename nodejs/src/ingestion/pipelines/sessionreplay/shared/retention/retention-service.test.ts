import { Redis } from 'ioredis'

import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { RedisPool, TeamId } from '~/types'

import { RetentionServiceMetrics } from './metrics'
import { RetentionService } from './retention-service'

const sessionSet = (...pairs: [number, string][]): SessionSet => {
    const set = new SessionSet()
    pairs.forEach(([teamId, sessionId]) => set.add(teamId, sessionId))
    return set
}

jest.mock('./metrics', () => ({
    RetentionServiceMetrics: {
        incrementLookupErrors: jest.fn(),
    },
}))

jest.mock('~/ingestion/pipelines/sessionreplay/sessions/metrics', () => ({
    SessionBatchMetrics: {
        observeRetentionRedisLatency: jest.fn(),
    },
}))

describe('RetentionService', () => {
    let retentionService: RetentionService
    let mockRedisClient: jest.Mocked<Redis>
    let mockPipeline: { set: jest.Mock; exec: jest.Mock }
    let mockTeamService: jest.Mocked<TeamService>

    beforeEach(() => {
        jest.useFakeTimers()

        mockPipeline = { set: jest.fn().mockReturnThis(), exec: jest.fn().mockResolvedValue([]) }
        mockRedisClient = {
            mget: jest.fn().mockResolvedValue([]),
            pipeline: jest.fn().mockReturnValue(mockPipeline),
        } as unknown as jest.Mocked<Redis>

        const mockRedisPool = {
            acquire: jest.fn().mockReturnValue(mockRedisClient),
            release: jest.fn(),
        } as unknown as jest.Mocked<RedisPool>

        mockTeamService = {
            getRetentionPeriodByTeamId: jest.fn().mockImplementation((teamId: TeamId) => {
                return {
                    1: '30d', // Valid
                    2: '1y', // Valid
                    3: null, // Missing
                    4: 'foobar', // Invalid
                }[teamId]
            }),
        } as unknown as jest.Mocked<TeamService>

        retentionService = new RetentionService(mockRedisPool, mockTeamService)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('resolveSessionRetentions', () => {
        it('returns an empty map without touching Redis for an empty set', async () => {
            const results = await retentionService.resolveSessionRetentions(sessionSet())
            expect(results.size).toBe(0)
            expect(mockRedisClient.mget).not.toHaveBeenCalled()
        })

        it('resolves cached hits in one MGET without hitting the team service', async () => {
            mockRedisClient.mget = jest.fn().mockResolvedValue(['30d', '1y'])

            const results = await retentionService.resolveSessionRetentions(sessionSet([1, 'a'], [2, 'b']))

            expect(results.get(1, 'a')).toEqual({ resolved: true, retentionPeriod: '30d' })
            expect(results.get(2, 'b')).toEqual({ resolved: true, retentionPeriod: '1y' })
            expect(mockRedisClient.mget).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.mget).toHaveBeenCalledWith([
                '@posthog/replay/session-retention-1-a',
                '@posthog/replay/session-retention-2-b',
            ])
            expect(mockTeamService.getRetentionPeriodByTeamId).not.toHaveBeenCalled()
            expect(mockPipeline.set).not.toHaveBeenCalled()
        })

        it('falls back to the team service for misses across teams, deduped per team, and caches each result', async () => {
            // sessions a and b share team 1 (→ 30d); session c is team 2 (→ 1y).
            mockRedisClient.mget = jest.fn().mockResolvedValue([null, null, null])

            const results = await retentionService.resolveSessionRetentions(sessionSet([1, 'a'], [1, 'b'], [2, 'c']))

            expect(results.get(1, 'a')).toEqual({ resolved: true, retentionPeriod: '30d' })
            expect(results.get(1, 'b')).toEqual({ resolved: true, retentionPeriod: '30d' })
            expect(results.get(2, 'c')).toEqual({ resolved: true, retentionPeriod: '1y' })
            // Three misses across two distinct teams → one team service lookup per team.
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledTimes(2)
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(1)
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(2)
            // Each resolved value is written back to its own key with a TTL.
            expect(mockPipeline.set).toHaveBeenCalledTimes(3)
            expect(mockPipeline.set).toHaveBeenCalledWith(
                '@posthog/replay/session-retention-1-a',
                '30d',
                'EX',
                24 * 60 * 60
            )
            expect(mockPipeline.set).toHaveBeenCalledWith(
                '@posthog/replay/session-retention-2-c',
                '1y',
                'EX',
                24 * 60 * 60
            )
            expect(mockPipeline.exec).toHaveBeenCalledTimes(1)
        })

        it('marks a session unresolvable (not thrown) when its team has no retention', async () => {
            mockRedisClient.mget = jest.fn().mockResolvedValue([null])

            const results = await retentionService.resolveSessionRetentions(sessionSet([3, 'gone']))

            expect(results.get(3, 'gone')).toEqual({ resolved: false })
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(3)
            expect(mockPipeline.set).not.toHaveBeenCalled()
            expect(RetentionServiceMetrics.incrementLookupErrors).toHaveBeenCalledTimes(1)
        })

        it('throws on a corrupt cached retention value', async () => {
            mockRedisClient.mget = jest.fn().mockResolvedValue(['foobar'])

            await expect(retentionService.resolveSessionRetentions(sessionSet([1, 'a']))).rejects.toThrow(
                "Invalid cached retention value 'foobar' for team 1 session a"
            )
            expect(mockTeamService.getRetentionPeriodByTeamId).not.toHaveBeenCalled()
            expect(mockPipeline.set).not.toHaveBeenCalled()
        })

        it('routes only misses to the team service and keys each result by (teamId, sessionId)', async () => {
            // session 'cached' (team 2) hits Redis; session 'miss' (team 1) misses and falls back.
            mockRedisClient.mget = jest.fn().mockResolvedValue(['1y', null])

            const results = await retentionService.resolveSessionRetentions(sessionSet([2, 'cached'], [1, 'miss']))

            expect(results.get(2, 'cached')).toEqual({ resolved: true, retentionPeriod: '1y' })
            expect(results.get(1, 'miss')).toEqual({ resolved: true, retentionPeriod: '30d' })
            // Only the miss goes to the team service; the hit does not.
            expect(mockTeamService.getRetentionPeriodByTeamId).toHaveBeenCalledWith(1)
            expect(mockTeamService.getRetentionPeriodByTeamId).not.toHaveBeenCalledWith(2)
            // Only the miss is written back to Redis.
            expect(mockPipeline.set).toHaveBeenCalledTimes(1)
            expect(mockPipeline.set).toHaveBeenCalledWith(
                '@posthog/replay/session-retention-1-miss',
                '30d',
                'EX',
                24 * 60 * 60
            )
        })

        it('scopes the cache key by team so the same session id across teams cannot collide', async () => {
            // Same session id under two teams: team 1 hits the cache (30d), team 2 misses (→ 1y).
            mockRedisClient.mget = jest.fn().mockResolvedValue(['30d', null])

            const results = await retentionService.resolveSessionRetentions(sessionSet([1, 's'], [2, 's']))

            // The shared session id is read under two distinct, team-scoped keys.
            expect(mockRedisClient.mget).toHaveBeenCalledWith([
                '@posthog/replay/session-retention-1-s',
                '@posthog/replay/session-retention-2-s',
            ])
            // Each team resolves to its own retention — no cross-team bleed from the cache.
            expect(results.get(1, 's')).toEqual({ resolved: true, retentionPeriod: '30d' })
            expect(results.get(2, 's')).toEqual({ resolved: true, retentionPeriod: '1y' })
            // Only team 2's miss is written back, under its own team-scoped key.
            expect(mockPipeline.set).toHaveBeenCalledTimes(1)
            expect(mockPipeline.set).toHaveBeenCalledWith(
                '@posthog/replay/session-retention-2-s',
                '1y',
                'EX',
                24 * 60 * 60
            )
        })

        it('propagates a Redis read failure (no team-service fallback, so the retry wrapper re-runs)', async () => {
            // Redis holds each session's locked-in retention, so we must not resolve from the
            // (current) team value on a Redis failure — fail fast and let the caller retry/crash.
            mockRedisClient.mget = jest.fn().mockRejectedValue(new Error('Command timed out'))

            await expect(retentionService.resolveSessionRetentions(sessionSet([1, 'a']))).rejects.toThrow(
                'Command timed out'
            )
            expect(mockTeamService.getRetentionPeriodByTeamId).not.toHaveBeenCalled()
        })
    })
})

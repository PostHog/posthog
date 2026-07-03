import { Redis } from 'ioredis'

import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { RedisPool } from '~/types'

import { SessionBatchMetrics } from './metrics'
import { SessionTracker } from './session-tracker'

jest.mock('./metrics', () => ({
    SessionBatchMetrics: {
        incrementNewSessionsDetected: jest.fn(),
        incrementSessionTrackerCacheHit: jest.fn(),
        incrementSessionTrackerCacheMiss: jest.fn(),
        incrementSessionTrackerRedisErrors: jest.fn(),
        observeSessionTrackerRedisLatency: jest.fn(),
    },
}))

const sessionSet = (...pairs: [number, string][]): SessionSet => {
    const set = new SessionSet()
    pairs.forEach(([teamId, sessionId]) => set.add(teamId, sessionId))
    return set
}

const TTL_SECONDS = 48 * 60 * 60

describe('SessionTracker', () => {
    let sessionTracker: SessionTracker
    let mockRedisClient: jest.Mocked<Redis>
    let mockPipeline: { set: jest.Mock; exec: jest.Mock }
    let mockRedisPool: jest.Mocked<RedisPool>

    beforeEach(() => {
        jest.clearAllMocks()

        mockPipeline = { set: jest.fn().mockReturnThis(), exec: jest.fn().mockResolvedValue([]) }
        mockRedisClient = {
            mget: jest.fn().mockResolvedValue([]),
            pipeline: jest.fn().mockReturnValue(mockPipeline),
        } as unknown as jest.Mocked<Redis>

        mockRedisPool = {
            acquire: jest.fn().mockResolvedValue(mockRedisClient),
            release: jest.fn(),
        } as unknown as jest.Mocked<RedisPool>

        sessionTracker = new SessionTracker(mockRedisPool, 5 * 60 * 1000)
    })

    describe('hasSeen', () => {
        it('reports new and already-seen sessions from a single MGET', async () => {
            mockRedisClient.mget = jest.fn().mockResolvedValue([null, '1'])

            const result = await sessionTracker.hasSeen(sessionSet([1, 'new'], [1, 'old']))

            expect(result.get(1, 'new')).toBe(false)
            expect(result.get(1, 'old')).toBe(true)
            expect(mockRedisClient.mget).toHaveBeenCalledTimes(1)
            expect(mockRedisClient.mget).toHaveBeenCalledWith([
                '@posthog/replay/session-seen:1:new',
                '@posthog/replay/session-seen:1:old',
            ])
        })

        it('returns an empty map without touching Redis for an empty set', async () => {
            const result = await sessionTracker.hasSeen(sessionSet())

            expect(result.size).toBe(0)
            expect(mockRedisPool.acquire).not.toHaveBeenCalled()
        })

        it('serves a marked session from the local cache without an MGET', async () => {
            await sessionTracker.markSeen(sessionSet([1, 'a']))

            const result = await sessionTracker.hasSeen(sessionSet([1, 'a']))

            expect(result.get(1, 'a')).toBe(true)
            expect(mockRedisClient.mget).not.toHaveBeenCalled()
            expect(SessionBatchMetrics.incrementSessionTrackerCacheHit).toHaveBeenCalledTimes(1)
        })

        it('caches a positive hit so the next check skips Redis, but rechecks a negative', async () => {
            mockRedisClient.mget = jest.fn().mockResolvedValue(['1'])
            await sessionTracker.hasSeen(sessionSet([1, 'seen']))
            await sessionTracker.hasSeen(sessionSet([1, 'seen']))
            // Positive was cached: only the first call hit Redis.
            expect(mockRedisClient.mget).toHaveBeenCalledTimes(1)

            mockRedisClient.mget = jest.fn().mockResolvedValue([null])
            await sessionTracker.hasSeen(sessionSet([1, 'unseen']))
            await sessionTracker.hasSeen(sessionSet([1, 'unseen']))
            // Negatives aren't cached, so an unseen session is rechecked every time.
            expect(mockRedisClient.mget).toHaveBeenCalledTimes(2)
        })

        it('fails safe by assuming unknown sessions are seen on a Redis error', async () => {
            mockRedisClient.mget = jest.fn().mockRejectedValue(new Error('Redis down'))

            const result = await sessionTracker.hasSeen(sessionSet([1, 'a']))

            // Assuming "seen" means we won't regenerate a key or re-consume the new-session budget.
            expect(result.get(1, 'a')).toBe(true)
            expect(SessionBatchMetrics.incrementSessionTrackerRedisErrors).toHaveBeenCalled()
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
        })
    })

    describe('markSeen', () => {
        it('sets each session key with a 48h TTL in one pipeline', async () => {
            await sessionTracker.markSeen(sessionSet([1, 'a'], [2, 'b']))

            expect(mockPipeline.set).toHaveBeenCalledWith('@posthog/replay/session-seen:1:a', '1', 'EX', TTL_SECONDS)
            expect(mockPipeline.set).toHaveBeenCalledWith('@posthog/replay/session-seen:2:b', '1', 'EX', TTL_SECONDS)
            expect(mockPipeline.exec).toHaveBeenCalledTimes(1)
            expect(SessionBatchMetrics.incrementNewSessionsDetected).toHaveBeenCalledTimes(2)
        })

        it('does nothing for an empty set', async () => {
            await sessionTracker.markSeen(sessionSet())

            expect(mockRedisPool.acquire).not.toHaveBeenCalled()
            expect(mockPipeline.set).not.toHaveBeenCalled()
        })

        it('fails open on a pipeline error', async () => {
            mockPipeline.exec = jest.fn().mockRejectedValue(new Error('Redis down'))

            await expect(sessionTracker.markSeen(sessionSet([1, 'a']))).resolves.toBeUndefined()
            expect(SessionBatchMetrics.incrementSessionTrackerRedisErrors).toHaveBeenCalled()
            expect(mockRedisPool.release).toHaveBeenCalledWith(mockRedisClient)
        })

        it('still records the session in the local cache when the pipeline write fails', async () => {
            mockPipeline.exec = jest.fn().mockRejectedValue(new Error('Redis down'))

            await sessionTracker.markSeen(sessionSet([1, 'a']))

            // Redis never persisted the mark, but this consumer must still treat the session as seen —
            // partition affinity keeps it here, so failing open without the local record would re-key
            // and re-charge the new-session budget for every session during a Redis blip.
            const result = await sessionTracker.hasSeen(sessionSet([1, 'a']))
            expect(result.get(1, 'a')).toBe(true)
            expect(mockRedisClient.mget).not.toHaveBeenCalled()
        })
    })
})

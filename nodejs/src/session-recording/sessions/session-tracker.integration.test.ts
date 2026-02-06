import { v4 as uuidv4 } from 'uuid'

import { RedisPool } from '../../types'
import { createRedisPoolFromConfig } from '../../utils/db/redis'
import { SessionTracker } from './session-tracker'

// nosemgrep: redis-unencrypted-transport (local testing only)
const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1'

describe('SessionTracker integration', () => {
    let redisPool: RedisPool
    let testRunId: string

    beforeAll(() => {
        redisPool = createRedisPoolFromConfig({
            connection: { url: REDIS_URL, name: 'session-tracker-integration-test' },
            poolMinSize: 1,
            poolMaxSize: 2,
        })
        testRunId = uuidv4()
    })

    afterAll(async () => {
        await redisPool.drain()
        await redisPool.clear()
    })

    describe('end-to-end session tracking', () => {
        it('should return true for new sessions and false for existing ones', async () => {
            const sessionTracker = new SessionTracker(redisPool, 100)
            const teamId = 1
            const sessionId = `new-session-${testRunId}-1`

            // First call should return true (new session)
            const isNew1 = await sessionTracker.trackSession(teamId, sessionId)
            expect(isNew1).toBe(true)

            // Second call should return false (session already exists)
            const isNew2 = await sessionTracker.trackSession(teamId, sessionId)
            expect(isNew2).toBe(false)
        })

        it('should persist session tracking across SessionTracker instances', async () => {
            const teamId = 3
            const sessionId = `persistent-session-${testRunId}`

            // Create first tracker and track session
            const tracker1 = new SessionTracker(redisPool, 100)
            const isNew1 = await tracker1.trackSession(teamId, sessionId)
            expect(isNew1).toBe(true)

            // Create a new tracker instance (simulating a new consumer)
            const tracker2 = new SessionTracker(redisPool, 100)

            // The session should already exist (fetched from Redis)
            const isNew2 = await tracker2.trackSession(teamId, sessionId)
            expect(isNew2).toBe(false)
        })

        it('should use local cache to avoid Redis calls', async () => {
            const teamId = 4
            const sessionId = `cached-session-${testRunId}`

            // Use a long cache TTL
            const trackerWithCache = new SessionTracker(redisPool, 5 * 60 * 1000)

            // First call goes to Redis and returns true
            const isNew1 = await trackerWithCache.trackSession(teamId, sessionId)
            expect(isNew1).toBe(true)

            // Second call should use cache and return false
            const isNew2 = await trackerWithCache.trackSession(teamId, sessionId)
            expect(isNew2).toBe(false)

            // Third call should also use cache
            const isNew3 = await trackerWithCache.trackSession(teamId, sessionId)
            expect(isNew3).toBe(false)
        })
    })
})

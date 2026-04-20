import { v4 as uuidv4 } from 'uuid'

import { createRedisPoolFromConfig } from '../../utils/db/redis'
import { SessionFilter, SessionFilterConfig } from './session-filter'

// nosemgrep: redis-unencrypted-transport (local testing only)
const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1'

describe('SessionFilter integration', () => {
    let sessionFilter: SessionFilter
    let redisPool: SessionFilterConfig['redisPool']
    let testRunId: string

    beforeAll(() => {
        redisPool = createRedisPoolFromConfig({
            connection: { url: REDIS_URL, name: 'session-filter-integration-test' },
            poolMinSize: 1,
            poolMaxSize: 2,
        })
        testRunId = uuidv4()
    })

    afterAll(async () => {
        await redisPool.drain()
        await redisPool.clear()
    })

    beforeEach(() => {
        sessionFilter = new SessionFilter({
            redisPool,
            bucketCapacity: 5,
            bucketReplenishRate: 1,
            blockingEnabled: true,
            filterEnabled: true,
            localCacheTtlMs: 100,
        })
    })

    describe('end-to-end rate limiting flow', () => {
        it('should block sessions when rate limit exceeded and persist to Redis', async () => {
            const teamId = 1

            // Create sessions until we hit the rate limit
            // Bucket capacity is 5, so 6th session should be blocked
            for (let i = 1; i <= 5; i++) {
                const sessionId = `${testRunId}-session-${i}`
                await sessionFilter.handleNewSession(teamId, sessionId)
                const isBlocked = await sessionFilter.isBlocked(teamId, sessionId)
                expect(isBlocked).toBe(false)
            }

            // 6th session should be rate limited and blocked
            const blockedSessionId = `${testRunId}-session-6`
            await sessionFilter.handleNewSession(teamId, blockedSessionId)
            const isBlocked = await sessionFilter.isBlocked(teamId, blockedSessionId)
            expect(isBlocked).toBe(true)
        })

        it('should persist blocked status across SessionFilter instances', async () => {
            const teamId = 2
            const sessionId = `${testRunId}-persistent-session`

            // Create first filter instance and block a session by exhausting rate limit
            const filter1 = new SessionFilter({
                redisPool,
                bucketCapacity: 1,
                bucketReplenishRate: 0.001,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 100,
            })

            // First session consumes the bucket
            await filter1.handleNewSession(teamId, `${testRunId}-first-session`)

            // Second session should be blocked
            await filter1.handleNewSession(teamId, sessionId)
            expect(await filter1.isBlocked(teamId, sessionId)).toBe(true)

            // Create a new filter instance (simulating a new consumer)
            const filter2 = new SessionFilter({
                redisPool,
                bucketCapacity: 1000,
                bucketReplenishRate: 1,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 100,
            })

            // The blocked session should still be blocked (fetched from Redis)
            const isBlockedInNewFilter = await filter2.isBlocked(teamId, sessionId)
            expect(isBlockedInNewFilter).toBe(true)

            // A new session that was never blocked should not be blocked
            const isNewSessionBlocked = await filter2.isBlocked(teamId, `${testRunId}-never-blocked`)
            expect(isNewSessionBlocked).toBe(false)
        })

        it('should not block sessions when blocking is disabled (dry run)', async () => {
            const teamId = 3

            const disabledFilter = new SessionFilter({
                redisPool,
                bucketCapacity: 1,
                bucketReplenishRate: 0.001,
                blockingEnabled: false,
                filterEnabled: true,
                localCacheTtlMs: 100,
            })

            // First session consumes the bucket
            await disabledFilter.handleNewSession(teamId, `${testRunId}-disabled-session-1`)

            // Second session would be rate limited but should NOT be blocked
            const session2 = `${testRunId}-disabled-session-2`
            await disabledFilter.handleNewSession(teamId, session2)
            expect(await disabledFilter.isBlocked(teamId, session2)).toBe(false)
        })

        it('should correctly cache blocked status locally', async () => {
            const teamId = 4

            const filter = new SessionFilter({
                redisPool,
                bucketCapacity: 1,
                bucketReplenishRate: 0.001,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 5 * 60 * 1000,
            })

            // Exhaust bucket and block a session
            await filter.handleNewSession(teamId, `${testRunId}-cache-first`)
            const blockedSession = `${testRunId}-cache-blocked`
            await filter.handleNewSession(teamId, blockedSession)

            // First isBlocked call goes to Redis
            const isBlocked1 = await filter.isBlocked(teamId, blockedSession)
            expect(isBlocked1).toBe(true)

            // Second call should be served from cache (we can't directly verify this
            // in integration test, but we can verify the result is consistent)
            const isBlocked2 = await filter.isBlocked(teamId, blockedSession)
            expect(isBlocked2).toBe(true)
        })
    })
})

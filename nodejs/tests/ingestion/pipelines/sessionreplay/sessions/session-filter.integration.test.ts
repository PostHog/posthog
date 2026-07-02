import { v4 as uuidv4 } from 'uuid'

import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { SessionFilter, SessionFilterConfig } from '~/ingestion/pipelines/sessionreplay/sessions/session-filter'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'

// nosemgrep: redis-unencrypted-transport (local testing only)
const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1'

// Single-session convenience over the batched isBlocked.
const blocked = (filter: SessionFilter, teamId: number, sessionId: string): Promise<boolean> =>
    filter.isBlocked(new SessionSet().add(teamId, sessionId)).then((m) => m.get(teamId, sessionId) ?? false)

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
                await sessionFilter.handleNewSessions(new SessionSet().add(teamId, sessionId))
                const isBlocked = await blocked(sessionFilter, teamId, sessionId)
                expect(isBlocked).toBe(false)
            }

            // 6th session should be rate limited and blocked
            const blockedSessionId = `${testRunId}-session-6`
            await sessionFilter.handleNewSessions(new SessionSet().add(teamId, blockedSessionId))
            const isBlocked = await blocked(sessionFilter, teamId, blockedSessionId)
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
            await filter1.handleNewSessions(new SessionSet().add(teamId, `${testRunId}-first-session`))

            // Second session should be blocked
            await filter1.handleNewSessions(new SessionSet().add(teamId, sessionId))
            expect(await blocked(filter1, teamId, sessionId)).toBe(true)

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
            const isBlockedInNewFilter = await blocked(filter2, teamId, sessionId)
            expect(isBlockedInNewFilter).toBe(true)

            // A new session that was never blocked should not be blocked
            const isNewSessionBlocked = await blocked(filter2, teamId, `${testRunId}-never-blocked`)
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
            await disabledFilter.handleNewSessions(new SessionSet().add(teamId, `${testRunId}-disabled-session-1`))

            // Second session would be rate limited but should NOT be blocked
            const session2 = `${testRunId}-disabled-session-2`
            await disabledFilter.handleNewSessions(new SessionSet().add(teamId, session2))
            expect(await blocked(disabledFilter, teamId, session2)).toBe(false)
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
            await filter.handleNewSessions(new SessionSet().add(teamId, `${testRunId}-cache-first`))
            const blockedSession = `${testRunId}-cache-blocked`
            await filter.handleNewSessions(new SessionSet().add(teamId, blockedSession))

            // First isBlocked call goes to Redis
            const isBlocked1 = await blocked(filter, teamId, blockedSession)
            expect(isBlocked1).toBe(true)

            // Second call should be served from cache (we can't directly verify this
            // in integration test, but we can verify the result is consistent)
            const isBlocked2 = await blocked(filter, teamId, blockedSession)
            expect(isBlocked2).toBe(true)
        })
    })

    describe('batch behavior', () => {
        it('blocks a mixed batch in one call and reads each session back from a fresh instance', async () => {
            const teamId = 5
            const allowed = `${testRunId}-batch-allowed`
            const blockedA = `${testRunId}-batch-blocked-a`
            const blockedB = `${testRunId}-batch-blocked-b`

            // Budget of 1: within a single batched call the first new session is allowed and the rest
            // are rate-limited and blocked. Verifies the pipelined write persists every blocked key.
            const writer = new SessionFilter({
                redisPool,
                bucketCapacity: 1,
                bucketReplenishRate: 0.001,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 100,
            })
            await writer.handleNewSessions(
                new SessionSet().add(teamId, allowed).add(teamId, blockedA).add(teamId, blockedB)
            )

            // A fresh instance (cold local cache) resolves the whole batch from Redis in one read.
            const reader = new SessionFilter({
                redisPool,
                bucketCapacity: 1000,
                bucketReplenishRate: 1,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 100,
            })
            const result = await reader.isBlocked(
                new SessionSet()
                    .add(teamId, allowed)
                    .add(teamId, blockedA)
                    .add(teamId, blockedB)
                    .add(teamId, `${testRunId}-batch-never`)
            )

            expect(result.get(teamId, allowed)).toBe(false)
            expect(result.get(teamId, blockedA)).toBe(true)
            expect(result.get(teamId, blockedB)).toBe(true)
            expect(result.get(teamId, `${testRunId}-batch-never`)).toBe(false)
        })

        it('keeps blocks isolated per team in Redis', async () => {
            const teamA = 6
            const teamB = 7
            const shared = `${testRunId}-team-shared`

            // Block (team A, shared) by exhausting team A's budget; team B is never touched.
            const writer = new SessionFilter({
                redisPool,
                bucketCapacity: 1,
                bucketReplenishRate: 0.001,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 100,
            })
            await writer.handleNewSessions(new SessionSet().add(teamA, `${testRunId}-team-filler`).add(teamA, shared))

            // A fresh instance reads both teams' identically-named session from Redis in one batch.
            const reader = new SessionFilter({
                redisPool,
                bucketCapacity: 1000,
                bucketReplenishRate: 1,
                blockingEnabled: true,
                filterEnabled: true,
                localCacheTtlMs: 100,
            })
            const result = await reader.isBlocked(new SessionSet().add(teamA, shared).add(teamB, shared))

            expect(result.get(teamA, shared)).toBe(true) // blocked in Redis for team A
            expect(result.get(teamB, shared)).toBe(false) // team B's key was never written
        })
    })
})

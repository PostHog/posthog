import { v4 as uuidv4 } from 'uuid'

import { createRedisPoolFromConfig } from '~/common/utils/db/redis'
import { SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { RedisPool } from '~/types'

// nosemgrep: redis-unencrypted-transport (local testing only)
const REDIS_URL = process.env.REDIS_URL || 'redis://127.0.0.1'

const sessionSet = (...pairs: [number, string][]): SessionSet => {
    const set = new SessionSet()
    pairs.forEach(([teamId, sessionId]) => set.add(teamId, sessionId))
    return set
}

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

    it('reports a session unseen until it is marked, then seen', async () => {
        const tracker = new SessionTracker(redisPool, 100)
        const teamId = 1
        const sessionId = `new-session-${testRunId}`

        expect((await tracker.hasSeen(sessionSet([teamId, sessionId]))).get(teamId, sessionId)).toBe(false)

        await tracker.markSeen(sessionSet([teamId, sessionId]))

        expect((await tracker.hasSeen(sessionSet([teamId, sessionId]))).get(teamId, sessionId)).toBe(true)
    })

    it('persists a marked session across tracker instances via Redis', async () => {
        const teamId = 3
        const sessionId = `persistent-session-${testRunId}`

        const tracker1 = new SessionTracker(redisPool, 100)
        expect((await tracker1.hasSeen(sessionSet([teamId, sessionId]))).get(teamId, sessionId)).toBe(false)
        await tracker1.markSeen(sessionSet([teamId, sessionId]))

        // A fresh instance (empty local cache) still sees it, because markSeen persisted to Redis.
        const tracker2 = new SessionTracker(redisPool, 100)
        expect((await tracker2.hasSeen(sessionSet([teamId, sessionId]))).get(teamId, sessionId)).toBe(true)
    })

    it('resolves a mixed batch of seen and unseen sessions in one call', async () => {
        const teamId = 4
        const seen = `seen-${testRunId}`
        const unseen = `unseen-${testRunId}`

        await new SessionTracker(redisPool, 5 * 60 * 1000).markSeen(sessionSet([teamId, seen]))

        // Fresh instance so the local cache doesn't pre-answer; the read must come from Redis (MGET).
        const result = await new SessionTracker(redisPool, 5 * 60 * 1000).hasSeen(
            sessionSet([teamId, seen], [teamId, unseen])
        )

        expect(result.get(teamId, seen)).toBe(true)
        expect(result.get(teamId, unseen)).toBe(false)
    })

    it('marks an entire batch seen in one call and reads them all back from a fresh instance', async () => {
        const teamId = 5
        const a = `batch-a-${testRunId}`
        const b = `batch-b-${testRunId}`
        const c = `batch-c-${testRunId}`

        await new SessionTracker(redisPool, 5 * 60 * 1000).markSeen(sessionSet([teamId, a], [teamId, b], [teamId, c]))

        // Fresh instance so the read comes from Redis: every key in the pipeline must have persisted.
        const result = await new SessionTracker(redisPool, 5 * 60 * 1000).hasSeen(
            sessionSet([teamId, a], [teamId, b], [teamId, c], [teamId, `batch-never-${testRunId}`])
        )

        expect(result.get(teamId, a)).toBe(true)
        expect(result.get(teamId, b)).toBe(true)
        expect(result.get(teamId, c)).toBe(true)
        expect(result.get(teamId, `batch-never-${testRunId}`)).toBe(false)
    })

    it('resolves a large interleaved batch across teams, matching each session to its own seen state', async () => {
        const teams = [10, 11, 12]
        const all = new SessionSet()
        const toMark = new SessionSet()
        const expectedSeen = new Map<string, boolean>()

        // Interleave seen/unseen within each team and across teams, so a misaligned MGET (result i
        // read against the wrong session) or a per-team key collision surfaces as a mismatch.
        for (const teamId of teams) {
            for (let i = 0; i < 8; i++) {
                const sessionId = `mixed-${teamId}-${i}-${testRunId}`
                const seen = i % 2 === 0
                all.add(teamId, sessionId)
                if (seen) {
                    toMark.add(teamId, sessionId)
                }
                expectedSeen.set(`${teamId}:${sessionId}`, seen)
            }
        }

        await new SessionTracker(redisPool, 5 * 60 * 1000).markSeen(toMark)

        // Fresh instance so every answer comes from Redis (MGET), not the local cache.
        const result = await new SessionTracker(redisPool, 5 * 60 * 1000).hasSeen(all)

        for (const { teamId, sessionId } of all) {
            expect(result.get(teamId, sessionId)).toBe(expectedSeen.get(`${teamId}:${sessionId}`))
        }
    })

    it('keeps seen state isolated per team in Redis', async () => {
        const teamA = 6
        const teamB = 7
        const shared = `team-shared-${testRunId}`

        await new SessionTracker(redisPool, 5 * 60 * 1000).markSeen(sessionSet([teamA, shared]))

        // A fresh instance reads both teams' identically-named session from Redis.
        const result = await new SessionTracker(redisPool, 5 * 60 * 1000).hasSeen(
            sessionSet([teamA, shared], [teamB, shared])
        )

        expect(result.get(teamA, shared)).toBe(true) // marked for team A
        expect(result.get(teamB, shared)).toBe(false) // team B was never marked
    })
})

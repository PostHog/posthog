import { RateLimiterRedis, RedisLlmRateLimiter } from './llm-rate-limiter'

// In-memory fake of the RedisV2 slice the limiter uses: a shared counter map with incr/expire.
function fakeRedis(): RateLimiterRedis & { store: Map<string, number>; fail: boolean } {
    const store = new Map<string, number>()
    return {
        store,
        fail: false,
        async useClient(_options, callback) {
            if (this.fail) {
                return null // simulate a Redis outage - useClient fails soft
            }
            return await callback({
                incr: (key: string) => {
                    const next = (store.get(key) ?? 0) + 1
                    store.set(key, next)
                    return Promise.resolve(next)
                },
                expire: () => Promise.resolve(1),
            })
        },
    }
}

describe('RedisLlmRateLimiter', () => {
    const caps = { defaultMaxCallsPerWorkflowPerMinute: 2, maxCallsPerTeamPerDay: 0 }

    it('allows calls up to the per-workflow cap and denies beyond it', async () => {
        const limiter = new RedisLlmRateLimiter(fakeRedis(), caps, () => 0)
        const call = () => limiter.check({ teamId: 1, workflowId: 'wf1' })

        expect((await call()).allowed).toBe(true)
        expect((await call()).allowed).toBe(true)
        const third = await call()
        expect(third.allowed).toBe(false)
        expect(third.reason).toContain('2 LLM calls/min')
    })

    it('honors a per-action override above the deployment default', async () => {
        const limiter = new RedisLlmRateLimiter(fakeRedis(), caps, () => 0)
        const call = () => limiter.check({ teamId: 1, workflowId: 'wf1', maxCallsPerMinute: 5 })

        for (let i = 0; i < 5; i++) {
            expect((await call()).allowed).toBe(true)
        }
        expect((await call()).allowed).toBe(false)
    })

    it('scopes the per-workflow counter to the current minute window', async () => {
        let now = 0
        const limiter = new RedisLlmRateLimiter(fakeRedis(), caps, () => now)

        await limiter.check({ teamId: 1, workflowId: 'wf1' })
        await limiter.check({ teamId: 1, workflowId: 'wf1' })
        expect((await limiter.check({ teamId: 1, workflowId: 'wf1' })).allowed).toBe(false)

        // Next minute: a fresh window resets the count.
        now = 60_000
        expect((await limiter.check({ teamId: 1, workflowId: 'wf1' })).allowed).toBe(true)
    })

    it('enforces the per-team daily backstop independently of the per-workflow cap', async () => {
        const limiter = new RedisLlmRateLimiter(
            fakeRedis(),
            { defaultMaxCallsPerWorkflowPerMinute: 0, maxCallsPerTeamPerDay: 1 },
            () => 0
        )

        expect((await limiter.check({ teamId: 9, workflowId: 'wf1' })).allowed).toBe(true)
        const denied = await limiter.check({ teamId: 9, workflowId: 'wf2' }) // different workflow, same team
        expect(denied.allowed).toBe(false)
        expect(denied.reason).toContain('calls/day')
    })

    it('fails open when Redis is unavailable', async () => {
        const redis = fakeRedis()
        redis.fail = true
        const limiter = new RedisLlmRateLimiter(redis, caps, () => 0)

        // Even past the cap, a Redis outage must not block workflows.
        for (let i = 0; i < 10; i++) {
            expect((await limiter.check({ teamId: 1, workflowId: 'wf1' })).allowed).toBe(true)
        }
    })
})

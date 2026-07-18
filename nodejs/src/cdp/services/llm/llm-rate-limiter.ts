// Cost/abuse guardrail for the LLM step (RFC §4). At dispatch time a step checks a per-workflow
// calls/minute cap and a per-team calls/day backstop, so a mis-authored workflow on a high-frequency
// trigger can't run up a bill before the gateway's own admission control kicks in. Fixed-window
// counters in Redis; fail-open so a Redis blip never blocks workflows (the gateway is the hard cap).

export interface LlmRateLimitDecision {
    allowed: boolean
    reason?: string
}

export interface LlmRateLimiter {
    check(args: { teamId: number; workflowId: string; maxCallsPerMinute?: number }): Promise<LlmRateLimitDecision>
}

// Default when no limiter is wired (tests, non-configured deployments): allow everything.
export class NoopLlmRateLimiter implements LlmRateLimiter {
    public check(): Promise<LlmRateLimitDecision> {
        return Promise.resolve({ allowed: true })
    }
}

export interface LlmRateLimiterCaps {
    // 0 = unlimited. Per-workflow default; an action's config.max_calls_per_minute overrides it.
    defaultMaxCallsPerWorkflowPerMinute: number
    maxCallsPerTeamPerDay: number
}

// The slice of RedisV2 we need. Declared narrowly so the limiter is testable with a fake.
export interface RateLimiterRedis {
    useClient<T>(
        options: { name: string },
        callback: (client: {
            incr(key: string): Promise<number>
            expire(key: string, ttl: number): Promise<unknown>
        }) => Promise<T>
    ): Promise<T | null>
}

export class RedisLlmRateLimiter implements LlmRateLimiter {
    constructor(
        private redis: RateLimiterRedis,
        private caps: LlmRateLimiterCaps,
        // Injectable for deterministic tests.
        private now: () => number = Date.now
    ) {}

    public async check(args: {
        teamId: number
        workflowId: string
        maxCallsPerMinute?: number
    }): Promise<LlmRateLimitDecision> {
        const perMinute = args.maxCallsPerMinute ?? this.caps.defaultMaxCallsPerWorkflowPerMinute
        if (perMinute > 0) {
            const bucket = Math.floor(this.now() / 60_000)
            const count = await this.incr(`llm:rl:wf:${args.workflowId}:${bucket}`, 60)
            if (count !== null && count > perMinute) {
                return { allowed: false, reason: `workflow exceeded ${perMinute} LLM calls/min` }
            }
        }

        if (this.caps.maxCallsPerTeamPerDay > 0) {
            const bucket = Math.floor(this.now() / 86_400_000)
            const count = await this.incr(`llm:rl:team:${args.teamId}:${bucket}`, 86_400)
            if (count !== null && count > this.caps.maxCallsPerTeamPerDay) {
                return { allowed: false, reason: `team exceeded ${this.caps.maxCallsPerTeamPerDay} LLM calls/day` }
            }
        }

        return { allowed: true }
    }

    // Fixed-window INCR: set the TTL only on the first increment of a window. Returns null on a Redis
    // failure (useClient fails soft), which the caller treats as "allowed" - fail-open.
    private incr(key: string, ttlSeconds: number): Promise<number | null> {
        return this.redis.useClient({ name: 'llm-rate-limiter' }, async (client) => {
            const count = await client.incr(key)
            if (count === 1) {
                await client.expire(key, ttlSeconds)
            }
            return count
        })
    }
}

import { Counter } from 'prom-client'

import { RedisClientPipeline, RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'

const guardOutcomeCounter = new Counter({
    name: 'error_tracking_per_issue_guard_outcome_total',
    help: 'Per-event outcome from the per-issue guarded rate limiter.',
    labelNames: ['outcome'],
})

export type GuardedStatus = 'allowed' | 'limited' | 'tripped' | 'fallback'

const STATUS_BY_CODE: GuardedStatus[] = ['allowed', 'limited', 'tripped', 'fallback']

export interface PerIssueGuardedRateLimiterConfig {
    /** Logical name; produces `@posthog/<name>/tokens|sigcount|sigfb/...` keys (`@posthog-test/...` under NODE_ENV=test). */
    name: string
    /** Max new bucket keys per team per window before tripping fallback. */
    threshold: number
    /** Counter window TTL (seconds). Also drives the hourly counter key rotation. */
    windowTtlSeconds: number
    /** Fallback flag TTL (seconds). How long a tripped team is quarantined from new-key creation. */
    fallbackTtlSeconds: number
    /** Token-bucket TTL (seconds). Mirrors the existing rate-limiter's bucket TTL. */
    bucketTtlSeconds: number
    /** When false, throw if the Redis pipeline returns null instead of fail-open allowing all. Default: true. */
    failOpen?: boolean
}

export interface PerIssueGuardedRequest {
    teamId: number
    sig: string
    cost: number
    bucketSize: number
    refillRate: number
    /** Override the request timestamp (seconds). Default: `Math.round(Date.now() / 1000)`. */
    now?: number
}

export interface PerIssueGuardedResult {
    tokensBefore: number
    tokens: number
    isRateLimited: boolean
    status: GuardedStatus
}

type GuardedPipeline = RedisClientPipeline & {
    checkGuardedRateLimit: (
        fallbackKey: string,
        counterKey: string,
        bucketKey: string,
        now: number,
        cost: number,
        bucketSize: number,
        refillRate: number,
        bucketExpiry: number,
        threshold: number,
        windowTtl: number,
        fallbackTtl: number
    ) => GuardedPipeline
}

const buildPrefixes = (name: string): { bucket: string; counter: string; fallback: string } => {
    const root = process.env.NODE_ENV === 'test' ? '@posthog-test' : '@posthog'
    return {
        bucket: `${root}/${name}/tokens`,
        counter: `${root}/${name}/sigcount`,
        fallback: `${root}/${name}/sigfb`,
    }
}

export class PerIssueGuardedRateLimiterService {
    private readonly prefixes: { bucket: string; counter: string; fallback: string }

    constructor(
        private readonly config: PerIssueGuardedRateLimiterConfig,
        private readonly redis: RedisV2
    ) {
        this.prefixes = buildPrefixes(config.name)
    }

    public getBucketKeyPrefix(): string {
        return this.prefixes.bucket
    }

    public getCounterKeyPrefix(): string {
        return this.prefixes.counter
    }

    public getFallbackKeyPrefix(): string {
        return this.prefixes.fallback
    }

    public bucketKey(teamId: number, sig: string): string {
        return `${this.prefixes.bucket}/${teamId}:exceptions:issue:${sig}`
    }

    public fallbackKey(teamId: number): string {
        return `${this.prefixes.fallback}/${teamId}`
    }

    public counterKey(teamId: number, nowSeconds: number): string {
        const window = Math.floor(nowSeconds / this.config.windowTtlSeconds)
        return `${this.prefixes.counter}/${teamId}/${window}`
    }

    public async rateLimit(requests: PerIssueGuardedRequest[]): Promise<Map<string, PerIssueGuardedResult>> {
        const out = new Map<string, PerIssueGuardedResult>()
        if (requests.length === 0) {
            return out
        }

        // Group by (teamId, sig). Sum costs across inputs that share a key so the
        // Lua script sees one call per unique sig (matches rateLimitGrouped shape).
        const grouped = new Map<string, PerIssueGuardedRequest>()
        for (const req of requests) {
            const id = this.bucketKey(req.teamId, req.sig)
            const existing = grouped.get(id)
            if (existing) {
                existing.cost += req.cost
            } else {
                grouped.set(id, { ...req })
            }
        }

        const items = [...grouped.entries()]

        const res = await this.redis.usePipeline(
            { name: `per-issue-guarded:${this.config.name}`, failOpen: true },
            (pipeline) => {
                for (const [, req] of items) {
                    const now = req.now ?? Math.round(Date.now() / 1000)
                    ;(pipeline as GuardedPipeline).checkGuardedRateLimit(
                        this.fallbackKey(req.teamId),
                        this.counterKey(req.teamId, now),
                        this.bucketKey(req.teamId, req.sig),
                        now,
                        req.cost,
                        req.bucketSize,
                        req.refillRate,
                        this.config.bucketTtlSeconds,
                        this.config.threshold,
                        this.config.windowTtlSeconds,
                        this.config.fallbackTtlSeconds
                    )
                }
            }
        )

        if (!res) {
            if (this.config.failOpen === false) {
                throw new Error(`PerIssueGuardedRateLimiterService(${this.config.name}): rate-limit pipeline failed`)
            }
            for (const [id, req] of items) {
                out.set(id, {
                    tokensBefore: req.bucketSize,
                    tokens: req.bucketSize,
                    isRateLimited: false,
                    status: 'allowed',
                })
            }
            guardOutcomeCounter.inc({ outcome: 'allowed' }, items.length)
            return out
        }

        items.forEach(([id, req], index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const raw = tokenRes?.[1] as [unknown, unknown, unknown] | undefined
            const tokensBefore = raw ? Number(raw[0]) : req.bucketSize
            const tokens = raw ? Number(raw[1]) : req.bucketSize
            const statusCode = raw ? Number(raw[2]) : 0
            const status = STATUS_BY_CODE[statusCode] ?? 'allowed'
            out.set(id, {
                tokensBefore,
                tokens,
                isRateLimited: status === 'limited',
                status,
            })
            guardOutcomeCounter.inc({ outcome: status }, 1)
        })

        return out
    }
}

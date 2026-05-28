import { Counter } from 'prom-client'

import { RedisClientPipeline, RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { KeyedRateLimit, KeyedRateLimitRequest, KeyedRateLimiter } from '~/common/services/keyed-rate-limiter.service'

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

export class PerIssueGuardedRateLimiterService implements KeyedRateLimiter {
    private readonly prefixes: { bucket: string; counter: string; fallback: string }

    constructor(
        private readonly config: PerIssueGuardedRateLimiterConfig,
        private readonly redis: RedisV2
    ) {
        this.prefixes = buildPrefixes(config.name)
    }

    public getKeyPrefix(): string {
        return this.prefixes.bucket
    }

    public getCounterKeyPrefix(): string {
        return this.prefixes.counter
    }

    public getFallbackKeyPrefix(): string {
        return this.prefixes.fallback
    }

    public fallbackKey(teamId: number): string {
        return `${this.prefixes.fallback}/${teamId}`
    }

    public counterKey(teamId: number, nowSeconds: number): string {
        const window = Math.floor(nowSeconds / this.config.windowTtlSeconds)
        return `${this.prefixes.counter}/${teamId}/${window}`
    }

    /**
     * Pluggable drop-in for the keyed-rate-limiter step. Mirrors the base
     * service's `rateLimitGrouped` shape so both services can be slotted into
     * the same spec list. `req.teamId` (populated by the step from `getTeamId`)
     * scopes the per-team counter and fallback flag — there's no id parsing,
     * the id itself stays opaque to this service apart from being passed to
     * Lua as the bucket-key suffix.
     *
     * Tripped/fallback statuses pass through as `isRateLimited: false`; the
     * team-global limiter downstream still gets to enforce. The full 4-state
     * status is exposed via the service's Prom counter so operators can
     * attribute trip events to specific teams.
     */
    public async rateLimitGrouped(requests: KeyedRateLimitRequest[]): Promise<[string, KeyedRateLimit][]> {
        if (requests.length === 0) {
            return []
        }

        const grouped = new Map<string, KeyedRateLimitRequest>()
        for (const req of requests) {
            const existing = grouped.get(req.id)
            if (existing) {
                existing.cost += req.cost
            } else {
                grouped.set(req.id, { ...req })
            }
        }

        const items = [...grouped.values()]

        const teamIds: number[] = items.map((req) => {
            if (req.teamId == null) {
                throw new Error(
                    `PerIssueGuardedRateLimiterService(${this.config.name}): request for id "${req.id}" is missing teamId — the step must populate it`
                )
            }
            return req.teamId
        })

        const bucketSizes = items.map((req) => {
            const bucketSize = req.bucketSize
            if (bucketSize == null) {
                throw new Error(
                    `PerIssueGuardedRateLimiterService(${this.config.name}): missing bucketSize for ${req.id}`
                )
            }
            return bucketSize
        })

        const res = await this.redis.usePipeline(
            { name: `per-issue-guarded:${this.config.name}`, failOpen: true },
            (pipeline) => {
                items.forEach((req, i) => {
                    const refillRate = req.refillRate
                    if (refillRate == null) {
                        throw new Error(
                            `PerIssueGuardedRateLimiterService(${this.config.name}): missing refillRate for ${req.id}`
                        )
                    }
                    const teamId = teamIds[i]
                    const now = req.now ?? Math.round(Date.now() / 1000)
                    ;(pipeline as GuardedPipeline).checkGuardedRateLimit(
                        this.fallbackKey(teamId),
                        this.counterKey(teamId, now),
                        `${this.prefixes.bucket}/${req.id}`,
                        now,
                        req.cost,
                        bucketSizes[i],
                        refillRate,
                        req.ttlSeconds ?? this.config.bucketTtlSeconds,
                        this.config.threshold,
                        this.config.windowTtlSeconds,
                        this.config.fallbackTtlSeconds
                    )
                })
            }
        )

        if (!res) {
            if (this.config.failOpen === false) {
                throw new Error(`PerIssueGuardedRateLimiterService(${this.config.name}): rate-limit pipeline failed`)
            }
            guardOutcomeCounter.inc({ outcome: 'allowed' }, requests.length)
            const bucketSizeById = new Map(items.map((req, i) => [req.id, bucketSizes[i]]))
            return requests.map((req) => {
                const bucketSize = bucketSizeById.get(req.id) ?? 0
                return [req.id, { tokensBefore: bucketSize, tokens: bucketSize, isRateLimited: false }]
            })
        }

        const budgetById = new Map<string, number>()
        const statusById = new Map<string, GuardedStatus>()
        items.forEach((req, index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            const raw = tokenRes?.[1] as [unknown, unknown, unknown] | undefined
            const tokensBefore = raw ? Number(raw[0]) : bucketSizes[index]
            const statusCode = raw ? Number(raw[2]) : 0
            const status = STATUS_BY_CODE[statusCode] ?? 'allowed'
            budgetById.set(req.id, tokensBefore)
            statusById.set(req.id, status)
        })

        const out: [string, KeyedRateLimit][] = requests.map((req) => {
            const status = statusById.get(req.id) ?? 'allowed'
            const tokensBefore = budgetById.get(req.id) ?? 0
            guardOutcomeCounter.inc({ outcome: status }, 1)

            if (status === 'tripped' || status === 'fallback') {
                // Skip client-side fan-out: per-issue defers to team-global limiter.
                return [req.id, { tokensBefore: 0, tokens: 0, isRateLimited: false }]
            }
            // Same fan-out shape as KeyedRateLimiterService.rateLimitGrouped.
            if (tokensBefore >= req.cost) {
                const next = tokensBefore - req.cost
                budgetById.set(req.id, next)
                return [req.id, { tokensBefore, tokens: next, isRateLimited: false }]
            }
            return [req.id, { tokensBefore, tokens: -1, isRateLimited: true }]
        })

        return out
    }
}

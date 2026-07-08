import { Counter } from 'prom-client'

import { RedisV2, getRedisPipelineResults } from '~/common/redis/redis-v2'
import { KeyedRateLimit, KeyedRateLimitRequest, KeyedRateLimiter } from '~/common/services/keyed-rate-limiter.service'
import { logger } from '~/common/utils/logger'

const guardOutcomeCounter = new Counter({
    name: 'error_tracking_per_issue_guard_outcome_total',
    help: 'Per-event outcome from the per-issue guarded rate limiter.',
    labelNames: ['outcome'],
})

export type GuardedStatus = 'allowed' | 'limited' | 'tripped' | 'cooldown'

/** `fail_open_redis`/`fail_open_lua` mark events allowed only by virtue of an error, so they can be alerted on. */
export type GuardOutcome = GuardedStatus | 'fail_open_redis' | 'fail_open_lua'

const STATUS_BY_CODE: GuardedStatus[] = ['allowed', 'limited', 'tripped', 'cooldown']

type ValidatedRequest = KeyedRateLimitRequest & { teamId: number; bucketSize: number; refillRate: number }

export interface PerIssueGuardedRateLimiterConfig {
    /** Logical name; produces `@posthog/<name>/tokens|sigcount|sigcooldown/...` keys (`@posthog-test/...` under NODE_ENV=test). */
    name: string
    /** Max new bucket keys per team per window before tripping cooldown. */
    threshold: number
    /** Counter window TTL (seconds). Also drives the hourly counter key rotation. */
    windowTtlSeconds: number
    /** Cooldown flag TTL (seconds). How long a tripped team is quarantined from new-key creation. */
    cooldownTtlSeconds: number
    /** Token-bucket TTL (seconds). Mirrors the existing rate-limiter's bucket TTL. */
    bucketTtlSeconds: number
    /** When false, throw if the Redis pipeline returns null instead of fail-open allowing all. Default: true. */
    failOpen?: boolean
}

const buildPrefixes = (name: string): { bucket: string; counter: string; cooldown: string } => {
    const root = process.env.NODE_ENV === 'test' ? '@posthog-test' : '@posthog'
    return {
        bucket: `${root}/${name}/tokens`,
        counter: `${root}/${name}/sigcount`,
        cooldown: `${root}/${name}/sigcooldown`,
    }
}

export class PerIssueGuardedRateLimiterService implements KeyedRateLimiter {
    private readonly prefixes: { bucket: string; counter: string; cooldown: string }

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

    public getCooldownKeyPrefix(): string {
        return this.prefixes.cooldown
    }

    // All three keys of a single guarded call carry a `{teamId}` hash tag so Redis Cluster
    // colocates them on one slot — the Lua script touches all three at once and would otherwise
    // fail with CROSSSLOT. Tagging on teamId keeps different teams spread across slots.
    public cooldownKey(teamId: number): string {
        return `${this.prefixes.cooldown}/{${teamId}}`
    }

    public counterKey(teamId: number, nowSeconds: number): string {
        const window = Math.floor(nowSeconds / this.config.windowTtlSeconds)
        return `${this.prefixes.counter}/{${teamId}}/${window}`
    }

    public bucketKey(teamId: number, id: string): string {
        return `${this.prefixes.bucket}/{${teamId}}/${id}`
    }

    /** Tripped/cooldown pass through as `isRateLimited: false`; the 4-state status only surfaces via the Prom counter. */
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

        const items = [...grouped.values()].map((req): ValidatedRequest => {
            if (req.teamId == null) {
                throw new Error(
                    `PerIssueGuardedRateLimiterService(${this.config.name}): request for id "${req.id}" is missing teamId — the step must populate it`
                )
            }
            if (req.bucketSize == null) {
                throw new Error(
                    `PerIssueGuardedRateLimiterService(${this.config.name}): missing bucketSize for ${req.id}`
                )
            }
            if (req.refillRate == null) {
                throw new Error(
                    `PerIssueGuardedRateLimiterService(${this.config.name}): missing refillRate for ${req.id}`
                )
            }
            return req as ValidatedRequest
        })

        const res = await this.redis.usePipeline(
            { name: `per-issue-guarded:${this.config.name}`, failOpen: true },
            (pipeline) => {
                items.forEach((req) => {
                    const now = req.now ?? Math.round(Date.now() / 1000)
                    pipeline.checkGuardedRateLimit(
                        this.cooldownKey(req.teamId),
                        this.counterKey(req.teamId, now),
                        this.bucketKey(req.teamId, req.id),
                        now,
                        req.cost,
                        req.bucketSize,
                        req.refillRate,
                        req.ttlSeconds ?? this.config.bucketTtlSeconds,
                        this.config.threshold,
                        this.config.windowTtlSeconds,
                        this.config.cooldownTtlSeconds
                    )
                })
            }
        )

        if (!res) {
            if (this.config.failOpen === false) {
                throw new Error(`PerIssueGuardedRateLimiterService(${this.config.name}): rate-limit pipeline failed`)
            }
            guardOutcomeCounter.inc({ outcome: 'fail_open_redis' }, requests.length)
            const bucketSizeById = new Map(items.map((req) => [req.id, req.bucketSize]))
            return requests.map((req) => {
                const bucketSize = bucketSizeById.get(req.id) ?? 0
                return [req.id, { tokensBefore: bucketSize, tokens: bucketSize, isRateLimited: false }]
            })
        }

        const budgetById = new Map<string, number>()
        const statusById = new Map<string, GuardedStatus>()
        const failOpenLuaIds = new Set<string>()
        items.forEach((req, index) => {
            const [tokenRes] = getRedisPipelineResults(res, index, 1)
            // Lua returns [tokensBefore, tokensAfter, statusCode]; we drop tokensAfter — it reflects
            // the summed cost, and we re-simulate per-input fan-out below.
            const callError = tokenRes?.[0]
            const raw = tokenRes?.[1] as [unknown, unknown, unknown] | undefined
            const tokensBefore = Number(raw?.[0])
            const statusCode = Number(raw?.[2])

            if (
                callError != null ||
                !Array.isArray(raw) ||
                raw.length < 3 ||
                Number.isNaN(tokensBefore) ||
                Number.isNaN(statusCode)
            ) {
                logger.warn('PerIssueGuardedRateLimiterService Lua call failed, failing open', {
                    name: this.config.name,
                    id: req.id,
                    teamId: req.teamId,
                    error: callError ?? undefined,
                    raw,
                })
                failOpenLuaIds.add(req.id)
                budgetById.set(req.id, req.bucketSize)
                return
            }

            const status = STATUS_BY_CODE[statusCode] ?? 'allowed'
            budgetById.set(req.id, tokensBefore)
            statusById.set(req.id, status)
        })

        const out: [string, KeyedRateLimit][] = requests.map((req) => {
            if (failOpenLuaIds.has(req.id)) {
                guardOutcomeCounter.inc({ outcome: 'fail_open_lua' }, 1)
                const bucketSize = budgetById.get(req.id) ?? 0
                return [req.id, { tokensBefore: bucketSize, tokens: bucketSize, isRateLimited: false }]
            }

            const status = statusById.get(req.id) ?? 'allowed'
            const tokensBefore = budgetById.get(req.id) ?? 0
            guardOutcomeCounter.inc({ outcome: status }, 1)

            if (status === 'tripped' || status === 'cooldown') {
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

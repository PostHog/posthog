import { Counter } from 'prom-client'

import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'
import { KeyedRateLimitRequest, KeyedRateLimiterService } from '~/common/services/keyed-rate-limiter.service'

import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { drop, ok } from '../pipelines/results'

const outcomeCounter = new Counter({
    name: 'keyed_rate_limiter_outcomes_total',
    help: 'Per-input rate limit outcomes for keyed rate limiters across pipelines.',
    labelNames: ['app_source', 'outcome', 'reporting_mode'],
})

export type RateLimitOutcome = 'allowed' | 'rate_limited'

export interface KeyedRateLimiterStepOptions<T> {
    /** When undefined, the step is a no-op — every input passes through `ok()`. */
    rateLimiter?: KeyedRateLimiterService
    /** When undefined, no `app_metrics2` rows are emitted; Prom counter still increments. */
    appMetricsAggregator?: AppMetricsAggregator
    /** Used as the `app_source` label on emitted metrics (e.g. 'exceptions'). */
    appSource: string
    /** Extract a stable rate-limit key from each input. Return null to skip rate-limiting that input. */
    getKey: (input: T) => string | null
    /** Cost per input. Defaults to 1 — override for byte-based limits etc. */
    getCost?: (input: T) => number
    /** Team id used when emitting `app_metrics2` rows. */
    getTeamId: (input: T) => number
    /**
     * Optional per-input override of bucketSize / refillRate / ttlSeconds. When provided,
     * the values from the first input in each key group win. All inputs sharing a key are
     * expected to agree (e.g. team-keyed limits where all inputs in a key share a team).
     */
    getBucketConfig?: (input: T) => Partial<Pick<KeyedRateLimitRequest, 'bucketSize' | 'refillRate' | 'ttlSeconds'>>
    /** When true, decisions are computed and tracked but never enforced — every input passes through `ok()`. */
    reportingMode: boolean
    /** Drop reason label when enforcing. Defaults to `rate_limited`. */
    dropReason?: string
}

/**
 * Generic batch pipeline step that applies a token-bucket rate limit keyed by
 * an arbitrary string. Reusable for the initial per-team exception limit and
 * for future per-hash / per-event-name limits — the only thing the caller
 * varies is `getKey`.
 *
 * Behaviour summary:
 * - rateLimiter undefined → no-op, all `ok()`.
 * - getKey returns null  → that input bypasses rate limiting (still `ok()`).
 * - reportingMode true   → decisions tracked but never enforced.
 * - reportingMode false  → inputs in rate-limited groups become `drop(dropReason)`.
 *
 * Cost is summed per unique key within a batch so we make one Redis call per key
 * regardless of how many inputs share it.
 */
export function createKeyedRateLimiterStep<T>(opts: KeyedRateLimiterStepOptions<T>): BatchProcessingStep<T, T> {
    const costFn = opts.getCost ?? (() => 1)
    const dropReason = opts.dropReason ?? 'rate_limited'
    const reportingModeLabel = opts.reportingMode ? 'true' : 'false'

    return async function keyedRateLimiterStep(inputs) {
        if (!opts.rateLimiter || inputs.length === 0) {
            return inputs.map((input) => ok(input))
        }

        // Per-input key (null means "skip this input"). Cost summed per unique key
        // so we issue exactly one Redis call per key — same pattern as logs-rate-limiter.
        // Bucket config (if provided) snapshots the first input per key — all inputs in
        // a key group are expected to agree (e.g. team-keyed limits all share a team).
        const keyForInput: (string | null)[] = new Array(inputs.length)
        const requestByKey = new Map<string, KeyedRateLimitRequest>()

        for (let i = 0; i < inputs.length; i++) {
            const key = opts.getKey(inputs[i])
            keyForInput[i] = key
            if (key === null) {
                continue
            }
            const inputCost = costFn(inputs[i])
            const existing = requestByKey.get(key)
            if (existing) {
                existing.cost += inputCost
            } else {
                const overrides = opts.getBucketConfig?.(inputs[i]) ?? {}
                requestByKey.set(key, { id: key, cost: inputCost, ...overrides })
            }
        }

        const limitedKeys = new Set<string>()
        if (requestByKey.size > 0) {
            const rateLimitResults = await opts.rateLimiter.rateLimitMany(Array.from(requestByKey.values()))
            for (const [key, result] of rateLimitResults) {
                if (result.isRateLimited) {
                    limitedKeys.add(key)
                }
            }
        }

        // Aggregate outcomes per (team, key, outcome) so we emit one app_metrics2
        // row per unique tuple regardless of input volume in this batch.
        const outcomeBuckets = new Map<
            string,
            { teamId: number; key: string; outcome: RateLimitOutcome; count: number }
        >()
        for (let i = 0; i < inputs.length; i++) {
            const key = keyForInput[i]
            if (key === null) {
                continue
            }
            const outcome: RateLimitOutcome = limitedKeys.has(key) ? 'rate_limited' : 'allowed'
            outcomeCounter.inc({ app_source: opts.appSource, outcome, reporting_mode: reportingModeLabel })

            if (opts.appMetricsAggregator) {
                const teamId = opts.getTeamId(inputs[i])
                const bucketKey = `${teamId}|${key}|${outcome}`
                const existing = outcomeBuckets.get(bucketKey)
                if (existing) {
                    existing.count++
                } else {
                    outcomeBuckets.set(bucketKey, { teamId, key, outcome, count: 1 })
                }
            }
        }

        if (opts.appMetricsAggregator) {
            for (const { teamId, key, outcome, count } of outcomeBuckets.values()) {
                opts.appMetricsAggregator.queue({
                    team_id: teamId,
                    app_source: opts.appSource,
                    app_source_id: key,
                    metric_kind: 'rate_limiting',
                    metric_name: outcome,
                    count,
                })
            }
        }

        return inputs.map((input, i) => {
            const key = keyForInput[i]
            if (key === null || !limitedKeys.has(key) || opts.reportingMode) {
                return ok(input)
            }
            return drop<T>(dropReason)
        })
    }
}

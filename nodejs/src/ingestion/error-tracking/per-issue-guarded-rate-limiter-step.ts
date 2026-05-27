import { Counter } from 'prom-client'

import { AppMetricsAggregator } from '~/common/services/app-metrics-aggregator'

import { BatchProcessingStep } from '../pipelines/base-batch-pipeline'
import { drop, ok } from '../pipelines/results'
import { GuardedStatus, PerIssueGuardedRateLimiterService } from './per-issue-guarded-rate-limiter.service'

const outcomeCounter = new Counter({
    name: 'error_tracking_per_issue_guarded_step_outcomes_total',
    help: 'Per-input outcomes for the per-issue guarded rate limiter step.',
    labelNames: ['outcome', 'reporting_mode'],
})

export interface PerIssueGuardedRateLimiterStepOptions<T> {
    rateLimiter?: PerIssueGuardedRateLimiterService
    appMetricsAggregator?: AppMetricsAggregator
    appSource: string
    /** Extract the team/sig pair to rate-limit on. Return null to skip this input. */
    getGuardKey: (input: T) => { teamId: number; sig: string } | null
    /** Cost per input. Defaults to 1. */
    getCost?: (input: T) => number
    /** Per-input bucket params; the first input in each (teamId, sig) group wins. */
    getBucketConfig: (input: T) => { bucketSize: number; refillRate: number }
    /** When true, decisions are computed and tracked but never enforced. */
    reportingMode: boolean
    /** Drop reason label when enforcing. Defaults to `rate_limited:per_issue_guarded`. */
    dropReason?: string
}

export function createPerIssueGuardedRateLimiterStep<T>(
    opts: PerIssueGuardedRateLimiterStepOptions<T>
): BatchProcessingStep<T, T> {
    const costFn = opts.getCost ?? (() => 1)
    const dropReason = opts.dropReason ?? 'rate_limited:per_issue_guarded'
    const reportingModeLabel = opts.reportingMode ? 'true' : 'false'

    return async function perIssueGuardedRateLimiterStep(inputs) {
        if (!opts.rateLimiter || inputs.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const guardKeyForInput: ({ teamId: number; sig: string } | null)[] = new Array(inputs.length)
        const statusForInput: GuardedStatus[] = new Array(inputs.length).fill('allowed')
        const requests: Parameters<PerIssueGuardedRateLimiterService['rateLimit']>[0] = []

        for (let i = 0; i < inputs.length; i++) {
            const guardKey = opts.getGuardKey(inputs[i])
            guardKeyForInput[i] = guardKey
            if (guardKey === null) {
                continue
            }
            const cfg = opts.getBucketConfig(inputs[i])
            requests.push({
                teamId: guardKey.teamId,
                sig: guardKey.sig,
                cost: costFn(inputs[i]),
                bucketSize: cfg.bucketSize,
                refillRate: cfg.refillRate,
            })
        }

        if (requests.length === 0) {
            return inputs.map((input) => ok(input))
        }

        const results = await opts.rateLimiter.rateLimit(requests)

        // Fan results back out across inputs sharing a guard key. The service
        // returns per-(teamId,sig) outcomes; inputs that share a key share an outcome.
        type Budget = { tokens: number; status: GuardedStatus }
        const budgetByKey = new Map<string, Budget>()
        for (let i = 0; i < inputs.length; i++) {
            const guardKey = guardKeyForInput[i]
            if (guardKey === null) {
                continue
            }
            const id = opts.rateLimiter.bucketKey(guardKey.teamId, guardKey.sig)
            const result = results.get(id)
            if (!result) {
                continue
            }
            if (!budgetByKey.has(id)) {
                budgetByKey.set(id, { tokens: result.tokensBefore, status: result.status })
            }
        }

        const outcomeBuckets = new Map<string, { teamId: number; key: string; outcome: GuardedStatus; count: number }>()

        for (let i = 0; i < inputs.length; i++) {
            const guardKey = guardKeyForInput[i]
            if (guardKey === null) {
                continue
            }
            const id = opts.rateLimiter.bucketKey(guardKey.teamId, guardKey.sig)
            const budget = budgetByKey.get(id)
            if (!budget) {
                continue
            }

            let outcome: GuardedStatus
            if (budget.status === 'tripped' || budget.status === 'fallback') {
                outcome = budget.status
            } else {
                const cost = costFn(inputs[i])
                if (budget.tokens >= cost) {
                    budget.tokens -= cost
                    outcome = 'allowed'
                } else {
                    outcome = 'limited'
                }
            }
            statusForInput[i] = outcome

            outcomeCounter.inc({ outcome, reporting_mode: reportingModeLabel })

            if (opts.appMetricsAggregator) {
                const bucketKey = `${guardKey.teamId}|${id}|${outcome}`
                const existing = outcomeBuckets.get(bucketKey)
                if (existing) {
                    existing.count++
                } else {
                    outcomeBuckets.set(bucketKey, {
                        teamId: guardKey.teamId,
                        key: id,
                        outcome,
                        count: 1,
                    })
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
            if (statusForInput[i] === 'limited' && !opts.reportingMode) {
                return drop<T>(dropReason)
            }
            return ok(input)
        })
    }
}

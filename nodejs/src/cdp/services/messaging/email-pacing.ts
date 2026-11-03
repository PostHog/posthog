import { Counter, Histogram } from 'prom-client'

import { HogFlowEmailSendingRateLimit, HogFlowEmailSendingRateLimitSchema } from '~/cdp/schema/hogflow'
import type { CyclotronJobInvocationHogFunction, HogFunctionType } from '~/cdp/types'

import type { RateLimiterService } from '../rate-limiter/rate-limiter.service'

const workflowEmailRateLimitedTotal = new Counter({
    name: 'cdp_workflow_email_rate_limited_total',
    help: 'Email sends delayed by a user-configured per-workflow sending rate limit.',
})

// The metadata blob is the flow action's config plus flow-level keys stamped in by
// HogFlowFunctionsService.buildHogFunction; parse defensively since it is untyped.
export function parseWorkflowEmailRateLimit(
    metadata: HogFunctionType['metadata']
): HogFlowEmailSendingRateLimit | null {
    const raw = metadata?.email_sending_rate_limit
    if (!raw) {
        return null
    }
    const parsed = HogFlowEmailSendingRateLimitSchema.safeParse(raw)
    return parsed.success ? parsed.data : null
}

export function pickTokenBucketRetryDelayMs(refillPerSecond: number): number {
    // Wake around when the next token accrues. The 1x-2x jitter spreads a queued backlog's
    // retries so they don't all re-dequeue (and re-claim against one token) at the same instant.
    // Clamped so second-scale limits don't churn the queue and hour-scale limits still wake
    // often enough to drain promptly once capacity frees up.
    const tokenIntervalMs = 1000 / refillPerSecond
    const baseMs = Math.min(Math.max(tokenIntervalMs, 1_000), 5 * 60 * 1_000)
    return Math.floor(baseMs * (1 + Math.random()))
}

// Bounds for the non-reserved cap retry delays (fallbacks and horizon overflow; a
// reserved slot is parked on exactly). The floor keeps second-scale refills from
// churning the queue. The ceiling bounds how stale the computed wake time can get:
// capacity can appear earlier than computed (a limit raise, or an idle bucket
// expiring back to full capacity), and a parked job only notices when it wakes.
const CAP_RETRY_MIN_MS = 1_000
export const CAP_RETRY_MAX_MS = 60 * 60 * 1_000

// How far denied sends park. Everything at or below the top bucket is a real slot.
// Above the top bucket is overflow: the backlog is deeper than one hour of refill.
// A sustained rate up there means a team queues more email than its limit can send.
export const emailReservedParkMs = new Histogram({
    name: 'cdp_email_reserved_park_ms',
    help: 'How far into the future a rate-limit-denied email parked, by limiter.',
    labelNames: ['limiter'],
    buckets: [1_000, 5_000, 15_000, 60_000, 300_000, 900_000, 1_800_000, 3_600_000],
})

export function pickReservedRetryDelayMs(
    retryAfterMs: number | null,
    refillPerSecond: number,
    reserved: boolean
): number {
    // No horizon means the limiter itself failed, not that the bucket was empty.
    // Wake on the short token-bucket cadence, not on a cap that paces in hours.
    if (retryAfterMs === null) {
        return pickTokenBucketRetryDelayMs(refillPerSecond)
    }
    // A reserved slot is the caller's own, exactly one token interval behind the slot
    // in front. Park on it as-is, with no floor: waking off the slot in either
    // direction means the token is not there (the bucket banks no surplus), the send
    // gets denied again, and it goes to the back of the line.
    if (reserved) {
        return retryAfterMs
    }
    const parkMs = Math.max(retryAfterMs, CAP_RETRY_MIN_MS)
    // Past the horizon nothing is reserved: every overflow caller got this same wake
    // time back. Spread them over the next horizon so they do not arrive as one herd
    // asking for tokens that will not be there.
    return Math.floor(parkMs * (1 + Math.random()))
}

export type SendDelay = {
    retryDelayMs: number
    logMessage: string
}

export class WorkflowPacing {
    constructor(private limiter: RateLimiterService | null) {}

    public async claim(invocation: CyclotronJobInvocationHogFunction, isTest: boolean): Promise<SendDelay | null> {
        const workflowRateLimit = parseWorkflowEmailRateLimit(invocation.hogFunction.metadata)
        if (!workflowRateLimit || !this.limiter || isTest) {
            return null
        }
        const periodSeconds = workflowRateLimit.period === 'minute' ? 60 : 3600
        const refillPerSecond = workflowRateLimit.count / periodSeconds
        // Burst capacity is about one second of budget, not the full count: a bucket that
        // could hold `count` starts full and refills within the same period, so a fresh (or
        // idle-expired) bucket would send ~2x the configured limit in its first period.
        // A near-empty bucket keeps every window at ~count and spreads sends evenly, which
        // is what the pacing is for.
        const capacity = Math.max(1, Math.ceil(refillPerSecond))
        const claim = await this.limiter.claimOrReserve(
            {
                key: `@posthog/workflow-email-rate/${invocation.teamId}/${invocation.functionId}`,
                requested: 1,
                capacity,
                refillPerSecond,
            },
            CAP_RETRY_MAX_MS
        )
        if (claim.granted !== 0) {
            return null
        }
        workflowEmailRateLimitedTotal.inc()
        const retryDelayMs = pickReservedRetryDelayMs(claim.retryAfterMs, refillPerSecond, claim.reserved)
        emailReservedParkMs.labels('workflow-email').observe(retryDelayMs)
        return {
            retryDelayMs,
            logMessage: `Sending rate limit reached (${workflowRateLimit.count} emails per ${workflowRateLimit.period}); retrying this email in ${Math.round(retryDelayMs / 1000)}s`,
        }
    }
}

import { Counter, Histogram } from 'prom-client'

import { HogFlowEmailSendingRateLimit, HogFlowEmailSendingRateLimitSchema } from '~/cdp/schema/hogflow'
import type { CyclotronJobInvocationHogFunction, HogFunctionType } from '~/cdp/types'
import { logger } from '~/common/utils/logger'

import type { TeamWorkflowsConfigService } from '../managers/team-workflows-config.service'
import type { RateLimiterService } from '../rate-limiter/rate-limiter.service'

export function pickThrottleRetryDelayMs(): number {
    // Constant 500–1000ms jitter is plenty: the local Valkey bucket already
    // gates re-dequeue at the configured refill rate, so a quick retry will
    // simply re-claim a token if SES capacity has refreshed. Exponential
    // backoff isn't needed at this layer.
    return 500 + Math.floor(Math.random() * 500)
}

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
const CAP_RETRY_MAX_MS = 60 * 60 * 1_000

// How far denied sends park. Everything at or below the top bucket is a real slot.
// Above the top bucket is overflow: the backlog is deeper than one hour of refill.
// A sustained rate up there means a team queues more email than its limit can send.
const emailReservedParkMs = new Histogram({
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

const teamEmailCapDelayedTotal = new Counter({
    name: 'cdp_team_email_cap_delayed_total',
    help: 'Workflow email sends delayed by the team trust-tier sending cap (or that would have been, in shadow mode).',
    labelNames: ['tier', 'bucket', 'mode'],
})

/**
 * Rollout mode for the per-team sending cap.
 *  - `off`: the cap is not consulted at all.
 *  - `shadow`: the cap is evaluated and every send it would delay is counted and logged, but no
 *    send is delayed. This is how the tier distribution is checked against real traffic before
 *    anything is enforced.
 *  - `enforce`: a denied claim reschedules the send.
 */
export type TeamEmailCapMode = 'off' | 'shadow' | 'enforce'

/** An unrecognized mode reads as `off`, so a typo in the env cannot start throttling teams. */
export function parseTeamEmailCapMode(value: string | undefined): TeamEmailCapMode {
    const mode = (value ?? '').trim().toLowerCase()
    return mode === 'shadow' || mode === 'enforce' ? mode : 'off'
}

/** Parses a comma-separated cap table. Any unusable entry drops the whole table, which turns the
 * cap off rather than applying a wrong number to a paying customer. */
export function parseTierCaps(value: string | undefined): number[] {
    const parts = (value ?? '')
        .split(',')
        .map((part) => part.trim())
        .filter((part) => part.length > 0)
    const caps = parts.map((part) => Number(part))
    if (caps.length === 0 || caps.some((cap) => !Number.isFinite(cap) || cap <= 0)) {
        return []
    }
    return caps
}

// Mirrors WORKFLOWS_EMAIL_TIER_HOURLY_CAPS / _DAILY_CAPS in posthog/settings/web.py. Both sides
// read the same tier index, so the two tables must stay in step.
const DEFAULT_TEAM_EMAIL_TIER_HOURLY_CAPS = [50, 200, 600, 2000, 6000, 20000, 60000, 200000]
const DEFAULT_TEAM_EMAIL_TIER_DAILY_CAPS = [100, 1000, 3000, 10000, 30000, 100000, 300000, 1000000]

// Comfortably longer than the window each bucket paces, so an idle bucket is never reset to full
// by expiry before it would have refilled on its own. Without that, a team that pauses for a day
// would get a fresh daily allowance instead of waiting for the refill.
const TEAM_EMAIL_HOUR_BUCKET_TTL_SECONDS = 6 * 60 * 60
const TEAM_EMAIL_DAY_BUCKET_TTL_SECONDS = 3 * 24 * 60 * 60

type TeamEmailCapBucket = {
    name: 'hour' | 'day'
    key: string
    capacity: number
    refillPerSecond: number
    ttlSeconds: number
    /** Cap and period as the customer sees them in the log line. */
    label: string
}

// The `{teamId}` hash tag puts both bucket keys in the same cluster slot. Enforce mode claims
// both keys in one Lua call (claimAllOrNothingPair), and clustered Valkey rejects a multi-key
// call whose keys hash to different slots with a CROSSSLOT error.
export function teamEmailCapBuckets(teamId: number, hourlyCap: number, dailyCap: number): TeamEmailCapBucket[] {
    return [
        {
            name: 'hour',
            key: `@posthog/team-email-rate-hour/{${teamId}}`,
            capacity: hourlyCap,
            refillPerSecond: hourlyCap / 3600,
            ttlSeconds: TEAM_EMAIL_HOUR_BUCKET_TTL_SECONDS,
            label: `${hourlyCap.toLocaleString('en-US')} emails per hour`,
        },
        {
            name: 'day',
            key: `@posthog/team-email-rate-day/{${teamId}}`,
            capacity: dailyCap,
            refillPerSecond: dailyCap / 86400,
            ttlSeconds: TEAM_EMAIL_DAY_BUCKET_TTL_SECONDS,
            label: `${dailyCap.toLocaleString('en-US')} emails per day`,
        },
    ]
}

export interface TeamEmailCapConfig {
    teamEmailCapMode?: TeamEmailCapMode
    teamEmailTierHourlyCaps?: number[]
    teamEmailTierDailyCaps?: number[]
}

type SendDelay = {
    retryDelayMs: number
    logMessage: string
}

export interface SendPacer {
    claim(
        invocation: CyclotronJobInvocationHogFunction,
        isTest: boolean,
        recipients?: number
    ): Promise<SendDelay | null>
}

export class WorkflowPacing implements SendPacer {
    constructor(private limiter: RateLimiterService | null) {}

    public async claim(invocation: CyclotronJobInvocationHogFunction, isTest: boolean): Promise<SendDelay | null> {
        const workflowRateLimit = parseWorkflowEmailRateLimit(invocation.hogFunction.metadata)
        if (workflowRateLimit && this.limiter && !isTest) {
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
            if (claim.granted === 0) {
                workflowEmailRateLimitedTotal.inc()
                const retryDelayMs = pickReservedRetryDelayMs(claim.retryAfterMs, refillPerSecond, claim.reserved)
                emailReservedParkMs.labels('workflow-email').observe(retryDelayMs)
                return {
                    retryDelayMs,
                    logMessage: `Sending rate limit reached (${workflowRateLimit.count} emails per ${workflowRateLimit.period}); retrying this email in ${Math.round(retryDelayMs / 1000)}s`,
                }
            }
        }
        return null
    }
}

export class TeamSendingCap implements SendPacer {
    constructor(
        private limiter: RateLimiterService | null,
        private teamWorkflowsConfigService: TeamWorkflowsConfigService,
        private config: TeamEmailCapConfig
    ) {}

    /**
     * Two buckets, not one: the daily cap bounds how much damage a team can do to the shared SES
     * account's reputation, and the hourly cap forces that volume to spread out so complaint
     * feedback (which lags by hours) arrives while the team's total volume is still small.
     *
     * Failure stances differ on purpose. A failed tier lookup lets the send through, because a
     * config blip must never throttle a legitimate customer. A failed bucket claim returns 0 from
     * the limiter, which delays the send, because we must not send when we cannot account for it.
     * A failed claim must not tell the customer it hit a cap, because none was reached.
     */
    public async claim(
        invocation: CyclotronJobInvocationHogFunction,
        isTest: boolean,
        recipients: number = 1
    ): Promise<SendDelay | null> {
        const mode: TeamEmailCapMode = this.config.teamEmailCapMode ?? 'off'
        if (mode === 'off' || isTest || !this.limiter) {
            return null
        }

        const teamTier = await this.teamWorkflowsConfigService.getEmailSendingTier(invocation.teamId)
        if (teamTier === null) {
            return null
        }

        const hourlyCaps = this.config.teamEmailTierHourlyCaps?.length
            ? this.config.teamEmailTierHourlyCaps
            : DEFAULT_TEAM_EMAIL_TIER_HOURLY_CAPS
        const dailyCaps = this.config.teamEmailTierDailyCaps?.length
            ? this.config.teamEmailTierDailyCaps
            : DEFAULT_TEAM_EMAIL_TIER_DAILY_CAPS
        const topTier = Math.min(hourlyCaps.length, dailyCaps.length) - 1
        if (topTier < 0) {
            return null
        }
        const tier = Math.min(Math.max(teamTier, 0), topTier)

        const buckets = teamEmailCapBuckets(invocation.teamId, hourlyCaps[tier], dailyCaps[tier])
        // Clamped to the smaller capacity: a send with more copies than a whole allowance could
        // never be granted and would reschedule forever. It charges the entire bucket instead, so
        // it still waits for full capacity and pays everything there is.
        const requested = Math.min(Math.max(1, recipients), buckets[0].capacity, buckets[1].capacity)

        if (mode === 'enforce') {
            // Both buckets in one atomic claim, granted whole or not at all. A denial consumes
            // nothing, so a rescheduled multi-recipient send cannot burn the partial refill on
            // every retry and starve the team's other emails while never sending itself.
            const claim = await this.limiter.claimAllOrNothingPair(
                [buckets[0], buckets[1]],
                requested,
                CAP_RETRY_MAX_MS
            )
            if (claim.granted) {
                return null
            }
            // `deniedIndex` is null when the limiter itself failed, not when a bucket was full. The
            // send still waits, because we must not send what we cannot account for, but no cap was
            // reached, so the log must not name a cap to the customer.
            const denied = claim.deniedIndex === null ? null : buckets[claim.deniedIndex]
            // The daily bucket paces a limiter failure because it is the slower of the two, so the
            // retry backs off at the safer rate while the limiter is unreachable.
            const pacing = denied ?? buckets[1]
            teamEmailCapDelayedTotal.inc({
                tier: String(tier),
                bucket: denied?.name ?? 'limiter_unavailable',
                mode,
            })
            const retryDelayMs = pickReservedRetryDelayMs(claim.retryAfterMs, pacing.refillPerSecond, claim.reserved)
            emailReservedParkMs.labels('team-email').observe(retryDelayMs)
            const capRetrySeconds = Math.round(retryDelayMs / 1000)
            return {
                retryDelayMs,
                logMessage: denied?.label
                    ? `This project reached its email sending limit of ${denied.label}. Retrying this email in ${capRetrySeconds}s. The limit rises as the project builds a clean sending history.`
                    : `Could not check this project's email sending limit, so this email is waiting. Retrying in ${capRetrySeconds}s. No action is needed on your side.`,
            }
        }

        // Shadow mode: the send goes out regardless, so drain each bucket by what the send costs
        // and log the first cap that would have delayed it, measuring both against real traffic.
        let firstDenial: TeamEmailCapBucket | null = null
        for (const bucket of buckets) {
            const granted = await this.limiter.claimUpTo({
                key: bucket.key,
                requested,
                capacity: bucket.capacity,
                refillPerSecond: bucket.refillPerSecond,
                ttlSeconds: bucket.ttlSeconds,
            })
            if (granted >= requested) {
                continue
            }
            teamEmailCapDelayedTotal.inc({ tier: String(tier), bucket: bucket.name, mode })
            firstDenial = firstDenial ?? bucket
        }

        if (firstDenial) {
            logger.info('📧', 'Team email sending cap would have delayed this send', {
                teamId: invocation.teamId,
                tier,
                bucket: firstDenial.name,
                cap: firstDenial.label,
            })
        }
        return null
    }
}

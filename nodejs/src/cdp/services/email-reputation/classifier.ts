/**
 * Pure classifier for email sender reputation, evaluated per workflow and per team.
 *
 * Each daily evaluation classifies the window's bounce/complaint rates against fixed
 * thresholds — there are no transitions or sticky states; every run recomputes from scratch.
 * Values mirror `posthog_emailreputationsnapshot.state`:
 * - insufficient_data: too few sends in the window to judge the rates
 * - healthy: below all warning thresholds
 * - warning: over a warning threshold
 * - critical: over a critical threshold (the level that will drive pausing once enforcement ships)
 */

export type ReputationState = 'insufficient_data' | 'healthy' | 'warning' | 'critical'

export interface ReputationThresholds {
    /** Below this many sends in the window, rates are too noisy to judge. */
    minSends: number
    bounceWarning: number
    bounceCritical: number
    complaintWarning: number
    complaintCritical: number
}

// Warn well before AWS's account-review lines (5% bounce / 0.1% complaint at ~0.5% escalation).
export const DEFAULT_THRESHOLDS: ReputationThresholds = {
    minSends: 100,
    bounceWarning: 0.02,
    bounceCritical: 0.05,
    complaintWarning: 0.001,
    complaintCritical: 0.005,
}

export interface ReputationMetrics {
    sent: number
    bounced: number
    complained: number
}

export interface ReputationClassification {
    state: ReputationState
    bounceRate: number
    complaintRate: number
}

export function classifyReputation(
    metrics: ReputationMetrics,
    thresholds: ReputationThresholds = DEFAULT_THRESHOLDS
): ReputationClassification {
    const bounceRate = metrics.sent > 0 ? metrics.bounced / metrics.sent : 0
    const complaintRate = metrics.sent > 0 ? metrics.complained / metrics.sent : 0

    let state: ReputationState
    if (metrics.sent < thresholds.minSends) {
        state = 'insufficient_data'
    } else if (complaintRate >= thresholds.complaintCritical || bounceRate >= thresholds.bounceCritical) {
        state = 'critical'
    } else if (complaintRate >= thresholds.complaintWarning || bounceRate >= thresholds.bounceWarning) {
        state = 'warning'
    } else {
        state = 'healthy'
    }

    return { state, bounceRate, complaintRate }
}

import type { CohortRealtimeReadinessApi } from '../generated/api.schemas'

// While history is being built, flags can't target the cohort yet, so the page keeps asking. The
// build takes tens of minutes, so this is slow polling, unlike the 1s loop the daily calculation uses.
export const REALTIME_POLL_INTERVAL_MS = 15_000

// A queued build and a running one are recorded in two places that do not overlap: a Redis key
// that expires exactly when the run-creation task fires, and the run row that task writes after sizing it. A
// poll landing between the two reads `needs_attention` for a build that is fine, so a cohort seen
// building keeps being checked for about three minutes. Long enough to cross that gap, and bounded, so
// a cohort nothing is preparing is not polled for as long as its page stays open.
export const READINESS_GRACE_POLLS = 12

export const isBuildingHistory = (cohort: { realtime?: CohortRealtimeReadinessApi | null } | undefined): boolean =>
    cohort?.realtime?.state === 'building' || cohort?.realtime?.state === 'rebuilding'

export function dailyReasonSentence(realtime: CohortRealtimeReadinessApi): string | null {
    switch (realtime.reason) {
        case 'unsupported_criteria':
            return "One of its criteria can't be matched in realtime, such as a sequence of events or a lifecycle criterion."
        case 'action_criteria':
            return "One of its criteria is an action, which realtime cohorts can't match on. Use events instead."
        case 'includes_non_realtime_cohort':
            return "It includes a cohort that isn't realtime. If that cohort becomes realtime, save this cohort again."
        case 'members_over_limit':
            // The API does not send this limit, so keep the number in sync with REALTIME_COHORT_MAX_PERSON_COUNT.
            return 'It has more than 20 million members, the most a realtime cohort can have.'
        case 'test_account_filter':
            return 'Realtime cohorts can\'t apply "Filter out internal and test users", which is on for this cohort. Turn it off in the cohort\'s criteria, then save the cohort.'
        case 'history_over_limit':
            return realtime.history_limit_days === null
                ? null
                : `Realtime cohorts on your plan can look back at most ${realtime.history_limit_days} days, and its criteria look back further. Its members come from the once-a-day calculation, which feature flags can't read.`
        default:
            return null
    }
}

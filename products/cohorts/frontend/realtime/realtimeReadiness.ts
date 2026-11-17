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

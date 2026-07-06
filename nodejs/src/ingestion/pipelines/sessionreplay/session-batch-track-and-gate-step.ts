import { Message } from 'node-rdkafka'

import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { ok } from '~/ingestion/framework/results'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { Gated, NewSessionFlag, SessionReplayHeaders } from './pipeline-types'
import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'

/**
 * Record-phase batch step: for the whole batch, learn which sessions are new, rate-limit the new ones
 * against their team's budget, and tag each element with `isNewSession` and a gate verdict (allowed vs
 * blocked) — all off the S3 write path, in a few batched Redis round-trips.
 *
 * Ordering matters: new sessions are rate-limited ({@link SessionFilter.handleNewSessions}, which
 * consumes one token per new session) BEFORE the block check, so a session that trips its own budget in
 * this batch is caught here. Because token consumption lives in this step's own retry scope, a
 * downstream key-resolution failure never re-runs it and double-charges the budget.
 *
 * Blocked sessions are NOT dropped here — they're tagged and carried through key resolution (which skips
 * them) to the mark-seen step, which marks every new session seen in one place and only then drops the
 * blocked ones. Marking a blocked session seen keeps it from being re-counted against the budget next
 * batch; dropping it only after mark-seen (rather than here) is what lets that marking be centralized.
 *
 * Redis failure policy (see {@link SessionTracker} and {@link SessionFilter} class docs): the two rules
 * split this step's Redis calls. {@link SessionTracker.hasSeen} decides generate-vs-fetch of the
 * encryption key, so it FAILS HARD — a Redis error throws and this whole step is retried by its wrapper
 * (which is safe: hasSeen runs first, before any token is consumed, so a retry can't double-charge). The
 * filter calls ({@link SessionFilter.handleNewSessions}/{@link SessionFilter.isBlocked}) are pure rate
 * limiting and fail open, so a Redis blip there under-limits rather than halting.
 */
/** The minimal per-element shape this step needs to track and rate-limit a session. */
type TrackAndGateStepInput = {
    message: Pick<Message, 'partition' | 'offset'>
    team: TeamForReplay
    headers: SessionReplayHeaders
    retentionPeriod: RetentionPeriod
}

export function createTrackAndGateStep<T extends TrackAndGateStepInput>(
    sessionTracker: SessionTracker,
    sessionFilter: SessionFilter
): BatchProcessingStep<T, Gated<T & NewSessionFlag>> {
    return async function trackAndGateStep(values) {
        // Dedupe repeated sessions so each one's Redis bootstrap runs exactly once per batch.
        const toResolve = new SessionSet()
        for (const value of values) {
            toResolve.add(value.team.teamId, value.headers.session_id)
        }

        // One batched Redis read tells us which sessions are new.
        const seen = await sessionTracker.hasSeen(toResolve)

        // Rate-limit the new sessions first (this may block some), before the batched block check —
        // so a session blocked by its own new-session budget in this batch is caught below.
        const newSessions = new SessionSet()
        for (const { teamId, sessionId } of toResolve) {
            if (!seen.get(teamId, sessionId)) {
                newSessions.add(teamId, sessionId)
            }
        }
        await sessionFilter.handleNewSessions(newSessions)

        // One batched Redis read tells us which sessions are blocked.
        const blocked = await sessionFilter.isBlocked(toResolve)

        return values.map((value) => {
            const teamId = value.team.teamId
            const sessionId = value.headers.session_id
            const isNewSession = !seen.get(teamId, sessionId)

            if (blocked.get(teamId, sessionId)) {
                return ok({ ...value, isNewSession, status: 'blocked' as const })
            }
            return ok({ ...value, isNewSession, status: 'allowed' as const })
        })
    }
}

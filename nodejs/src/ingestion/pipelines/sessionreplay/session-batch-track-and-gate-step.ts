import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { Allowed, NewSessionFlag, SessionReplayHeaders } from './pipeline-types'
import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'

/** The minimal per-element shape this step needs to track and rate-limit a session. */
type TrackAndGateStepInput = {
    message: Pick<Message, 'partition' | 'offset'>
    team: TeamForReplay
    headers: SessionReplayHeaders
    retentionPeriod: RetentionPeriod
}

/**
 * Record-phase batch step: for the whole batch, learn which sessions are new, rate-limit the new ones
 * against their team's budget, and either tag each surviving element with `isNewSession` (allowed, on to
 * key resolution) or drop it as blocked — all off the S3 write path, in a few batched Redis round-trips.
 *
 * Ordering matters: the block check runs BEFORE rate-limiting, and only sessions that are neither seen
 * nor already blocked are charged a token ({@link SessionFilter.handleNewSessions} consumes one per
 * genuinely-new session). An already-blocked session is kept out of the budget by its own block key, not
 * by charging it again — so a session dropped for the rest of its life doesn't drain its team's budget
 * every batch. A session that trips its own budget in this batch is caught by unioning the newly-blocked
 * set that handleNewSessions returns with the earlier block read.
 *
 * Blocked sessions are dropped right here. They carry no key, so nothing downstream acts on them — key
 * resolution would skip them and the mark-seen step would only drop them — and, crucially, a blocked
 * session is never marked seen: the block key alone keeps it out of the budget and out of recording, so
 * the seen flag stays strictly "a key exists". That decoupling makes a lost block key degrade to an extra
 * token charge next batch (tolerable) rather than a keyless, cleartext recording.
 *
 * Redis failure policy (see {@link SessionTracker} and {@link SessionFilter} class docs): the two rules
 * split this step's Redis calls. {@link SessionTracker.hasSeen} decides generate-vs-fetch of the
 * encryption key, so it FAILS HARD — a Redis error throws and this whole step is retried by its wrapper
 * (which is safe: hasSeen runs first, before any token is consumed, so a retry can't double-charge). The
 * filter calls ({@link SessionFilter.handleNewSessions}/{@link SessionFilter.isBlocked}) are pure rate
 * limiting and fail open, so a Redis blip there under-limits rather than halting.
 */
export function createTrackAndGateStep<T extends TrackAndGateStepInput>(
    sessionTracker: SessionTracker,
    sessionFilter: SessionFilter
): ChunkProcessingStep<T, Allowed<T & NewSessionFlag>> {
    return async function trackAndGateStep(values) {
        // Dedupe repeated sessions so each one's Redis bootstrap runs exactly once per batch.
        const toResolve = new SessionSet()
        for (const value of values) {
            toResolve.add(value.team.teamId, value.headers.session_id)
        }

        // One batched Redis read tells us which sessions are new.
        const seen = await sessionTracker.hasSeen(toResolve)

        // And one tells us which are already blocked — read before charging, so a session already on the
        // blocklist isn't re-counted against its team's budget.
        const alreadyBlocked = await sessionFilter.isBlocked(toResolve)

        // Charge a token only for genuinely-new sessions: neither seen nor already blocked. This may
        // block some more; handleNewSessions returns exactly the set it just blocked.
        const newSessions = new SessionSet()
        for (const { teamId, sessionId } of toResolve) {
            if (!seen.get(teamId, sessionId) && !alreadyBlocked.has(teamId, sessionId)) {
                newSessions.add(teamId, sessionId)
            }
        }
        const newlyBlocked = await sessionFilter.handleNewSessions(newSessions)

        return values.map((value) => {
            const teamId = value.team.teamId
            const sessionId = value.headers.session_id
            const isNewSession = !seen.get(teamId, sessionId)

            if (alreadyBlocked.has(teamId, sessionId) || newlyBlocked.has(teamId, sessionId)) {
                logger.debug('🔁', 'session_replay_session_dropped_before_record', {
                    sessionId,
                    teamId,
                    reason: 'session_blocked',
                })
                return drop<Allowed<T & NewSessionFlag>>('session_blocked')
            }
            return ok({ ...value, isNewSession, status: 'allowed' as const })
        })
    }
}

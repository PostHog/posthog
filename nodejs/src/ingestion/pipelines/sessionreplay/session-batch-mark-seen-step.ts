import { logger } from '~/common/utils/logger'
import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { NewSessionFlag, Recordable, Resolved, SessionReplayHeaders } from './pipeline-types'
import { SessionTracker } from './sessions/session-tracker'

/** The minimal per-element shape this step needs to mark a session seen. */
type MarkSeenStepInput = { team: TeamForReplay; headers: SessionReplayHeaders } & NewSessionFlag

/**
 * Record-phase batch step: mark new sessions as seen, in one Redis pipeline, now that key resolution has
 * run upstream — then drop the deleted sessions, so only recordable (allowed, keyed) sessions pass on.
 *
 * Only allowed and deleted sessions reach this step (blocked ones are dropped at the gate). This is the
 * single place sessions are marked seen, and a session is marked only once the keystore holds a durable
 * entry for it — so the seen flag means strictly "a later `getKey` for this session resolves to something
 * other than cleartext." That holds for both statuses here: `allowed` has a real key generated/fetched,
 * and `deleted` has a tombstone whose 30-day TTL outlives the seen flag, so while seen it always resolves
 * as deleted. (A `blocked` session — keyless and tombstone-less — would break this, which is exactly why
 * it's dropped upstream and never reaches here.) Marking earlier, before resolution, would risk a keyless
 * cleartext recording on a key-resolution retry.
 */
export function createMarkSeenStep<T extends MarkSeenStepInput>(
    sessionTracker: SessionTracker
): BatchProcessingStep<Resolved<T>, Recordable<T>> {
    return async function markSeenStep(values) {
        const newlySeen = new SessionSet()
        for (const value of values) {
            // Allowed has a key, deleted has a tombstone — both are safe to mark seen (a later getKey
            // resolves to the key or to 'deleted', never cleartext).
            if (value.isNewSession) {
                newlySeen.add(value.team.teamId, value.headers.session_id)
            }
        }

        await sessionTracker.markSeen(newlySeen)

        return values.map((value) => {
            if (value.status === 'allowed') {
                return ok(value)
            }
            logger.debug('🔁', 'session_replay_session_dropped_before_record', {
                sessionId: value.headers.session_id,
                teamId: value.team.teamId,
                reason: 'session_deleted',
            })
            return drop<Recordable<T>>('session_deleted')
        })
    }
}

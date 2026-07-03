import { logger } from '~/common/utils/logger'
import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { NewSessionFlag, Resolved, SessionReplayHeaders } from './pipeline-types'
import { SessionTracker } from './sessions/session-tracker'

/**
 * Record-phase batch step: mark every new session in the batch as seen, in one Redis pipeline, now that
 * each session's key has been durably resolved upstream — then drop the sessions that won't be recorded
 * (blocked or deleted).
 *
 * This is the single place sessions are marked seen. Marking earlier — before the key exists — would, on
 * a key-resolution retry, make a session read as existing and fetch a key that was never generated,
 * recording cleartext. Blocked and deleted sessions are marked here too (so they aren't re-counted
 * against the rate limit every batch) and only then dropped: they never carry a key, but marking a
 * keyless session seen is safe — a blocked session's block flag shares the seen TTL, and a deleted
 * session's tombstone outlives it, so either stays dropped (blocked / deleted) for as long as it's seen.
 */
export function createMarkSeenStep<T extends { team: TeamForReplay; headers: SessionReplayHeaders } & NewSessionFlag>(
    sessionTracker: SessionTracker
): BatchProcessingStep<Resolved<T>, T & { status: 'allowed'; sessionKey: SessionKey }> {
    return async function markSeenStep(values) {
        const newlySeen = new SessionSet()
        for (const value of values) {
            if (value.isNewSession) {
                newlySeen.add(value.team.teamId, value.headers.session_id)
            }
        }

        await sessionTracker.markSeen(newlySeen)

        return values.map((value) => {
            if (value.status === 'allowed') {
                return ok(value)
            }
            const reason = value.status === 'blocked' ? 'session_blocked' : 'session_deleted'
            logger.debug('🔁', 'session_replay_session_dropped_before_record', {
                sessionId: value.headers.session_id,
                teamId: value.team.teamId,
                reason,
            })
            return drop<T & { status: 'allowed'; sessionKey: SessionKey }>(reason)
        })
    }
}

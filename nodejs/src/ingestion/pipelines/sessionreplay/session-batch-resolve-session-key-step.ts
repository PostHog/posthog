import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { RetentionPeriod, RetentionPeriodToDaysMap } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { KeyStore, SessionKey } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'
import { SessionReplayHeaders } from './validate-headers-step'

/** A session either resolves to its encryption key, or is dropped before it reaches the recorder. */
type SessionResolution = { sessionKey: SessionKey } | { drop: string }

/**
 * Record-phase batch step: run each session's new-session bootstrap for the whole batch — off the S3
 * write path — and attach the resolved encryption key to every element, before the message is parsed
 * and recorded.
 *
 * For each distinct `(teamId, sessionId)` (deduped via a {@link SessionSet}, so the work runs once
 * per session even when the batch holds many of its messages):
 * - check whether the session has been seen before ({@link SessionTracker.hasSeen}) to learn whether
 *   it's new;
 * - for a new session, run the new-session rate limiter ({@link SessionFilter.handleNewSessions}),
 *   which may block a team that's over its new-session budget — this consumes one token per new
 *   session, which is exactly why the work must be deduped and not repeated per message;
 * - drop the session if it's blocked;
 * - resolve its key — {@link KeyStore.generateKey} for a new session (using the retention resolved
 *   upstream to set the key's expiry), {@link KeyStore.getKey} otherwise — and drop it if the key
 *   has been deleted;
 * - mark the session seen ({@link SessionTracker.markSeen}) only after its key has been resolved, so a
 *   keystore failure leaves it unseen and the retry regenerates rather than fetching a key that was
 *   never generated (which would record cleartext).
 *
 * Keys on the `session_id` header, which {@link createValidateSessionReplayHeadersStep} guarantees is
 * present, and on the retention resolved by {@link createResolveRetentionStep}, so it must run after
 * both. A transient failure (e.g. keystore Redis/KMS) throws so the pipeline's retry wrapper can
 * re-run the step; the tracker and filter fail open on Redis errors, matching prior behavior. A
 * dropped message still commits its offset — the drop result flows out of the pipeline carrying its
 * source message, so the single offset-tracking stage picks it up.
 */
export function createResolveSessionKeyStep<
    T extends {
        message: Pick<Message, 'partition' | 'offset'>
        team: TeamForReplay
        headers: SessionReplayHeaders
        retentionPeriod: RetentionPeriod
    },
>(
    sessionTracker: SessionTracker,
    sessionFilter: SessionFilter,
    keyStore: KeyStore
): BatchProcessingStep<T, T & { sessionKey: SessionKey }> {
    return async function resolveSessionKeyStep(values) {
        // Dedupe repeated sessions so each one's Redis bootstrap runs exactly once per batch.
        const toResolve = new SessionSet()
        const retentionBySession = new SessionMap<RetentionPeriod>()
        for (const value of values) {
            toResolve.add(value.team.teamId, value.headers.session_id)
            retentionBySession.set(value.team.teamId, value.headers.session_id, value.retentionPeriod)
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

        const resolutions = new SessionMap<SessionResolution>()
        const newlySeen = new SessionSet()
        await Promise.all(
            [...toResolve].map(async ({ teamId, sessionId }) => {
                const isNewSession = !seen.get(teamId, sessionId)

                let resolution: SessionResolution
                if (blocked.get(teamId, sessionId)) {
                    resolution = { drop: 'session_blocked' }
                } else {
                    const retentionPeriod = retentionBySession.get(teamId, sessionId)!
                    // A keystore failure throws here, aborting the batch before the markSeen below, so
                    // the retry regenerates instead of marking a session seen without a key.
                    const sessionKey = isNewSession
                        ? await keyStore.generateKey(sessionId, teamId, RetentionPeriodToDaysMap[retentionPeriod])
                        : await keyStore.getKey(sessionId, teamId)
                    resolution = sessionKey.sessionState === 'deleted' ? { drop: 'session_deleted' } : { sessionKey }
                }

                if (isNewSession) {
                    newlySeen.add(teamId, sessionId)
                }
                resolutions.set(teamId, sessionId, resolution)
            })
        )

        // Mark the new sessions seen in one batched write, only now that every key has been durably
        // resolved. Marking on the initial check instead would, on a keystore retry, make a session
        // read as existing and fetch a key that was never generated — recording cleartext.
        await sessionTracker.markSeen(newlySeen)

        return values.map((value) => {
            const resolution = resolutions.get(value.team.teamId, value.headers.session_id)!
            if ('drop' in resolution) {
                logger.debug('🔁', 'session_replay_session_dropped_before_record', {
                    sessionId: value.headers.session_id,
                    teamId: value.team.teamId,
                    reason: resolution.drop,
                })
                return drop(resolution.drop)
            }
            return ok({ ...value, sessionKey: resolution.sessionKey })
        })
    }
}

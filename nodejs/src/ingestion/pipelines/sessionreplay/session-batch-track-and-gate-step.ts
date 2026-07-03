import { Message } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { NewSessionFlag } from './pipeline-types'
import { SessionFilter } from './sessions/session-filter'
import { SessionTracker } from './sessions/session-tracker'
import { SessionReplayHeaders } from './validate-headers-step'

/**
 * Record-phase batch step: for the whole batch, learn which sessions are new, rate-limit the new ones
 * against their team's budget, and drop the ones that end up blocked — all off the S3 write path, in a
 * few batched Redis round-trips. It tags every surviving element with `isNewSession` so the downstream
 * per-session key resolution knows whether to generate or fetch a key.
 *
 * Ordering matters: new sessions are rate-limited ({@link SessionFilter.handleNewSessions}, which
 * consumes one token per new session) BEFORE the block check, so a session that trips its own budget in
 * this batch is caught here. Because token consumption lives in this step's own retry scope, a
 * downstream key-resolution failure never re-runs it and double-charges the budget.
 *
 * A blocked new session is marked seen here (it's dropped and never reaches the key step), so it isn't
 * re-rate-limited next batch. Sessions that survive are marked seen only after their key is durably
 * resolved (see {@link createMarkSeenStep}). A dropped message still commits its offset — the drop flows
 * out carrying its source message for the single offset-tracking stage (see {@link runSessionReplayPipeline}).
 */
export function createTrackAndGateStep<
    T extends {
        message: Pick<Message, 'partition' | 'offset'>
        team: TeamForReplay
        headers: SessionReplayHeaders
        retentionPeriod: RetentionPeriod
    },
>(sessionTracker: SessionTracker, sessionFilter: SessionFilter): BatchProcessingStep<T, T & NewSessionFlag> {
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

        // Blocked new sessions drop here, so mark them seen now — they never reach the key step, and
        // marking them keeps them from being rate-limited again next batch.
        const blockedNewlySeen = new SessionSet()
        const results = values.map((value) => {
            const teamId = value.team.teamId
            const sessionId = value.headers.session_id
            const isNewSession = !seen.get(teamId, sessionId)

            if (blocked.get(teamId, sessionId)) {
                if (isNewSession) {
                    blockedNewlySeen.add(teamId, sessionId)
                }
                logger.debug('🔁', 'session_replay_session_dropped_before_record', {
                    sessionId,
                    teamId,
                    reason: 'session_blocked',
                })
                return drop<T & NewSessionFlag>('session_blocked')
            }

            return ok({ ...value, isNewSession })
        })

        await sessionTracker.markSeen(blockedNewlySeen)

        return results
    }
}

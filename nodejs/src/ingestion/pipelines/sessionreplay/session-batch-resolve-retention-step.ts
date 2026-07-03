import { logger } from '~/common/utils/logger'
import { BatchProcessingStep } from '~/ingestion/framework/base-batch-pipeline'
import { drop, ok } from '~/ingestion/framework/results'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { RetentionPeriod } from '~/ingestion/pipelines/sessionreplay/shared/constants'
import { RetentionService } from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'

import { SessionReplayHeaders } from './pipeline-types'
import { SessionBatchMetrics } from './sessions/metrics'

/**
 * Record-phase batch step: resolve per-session retention for the whole batch and attach it to each
 * element, before the message is parsed and recorded — so retention is resolved off the S3 write
 * path, and a session bound for the wrong retention is never parsed or written.
 *
 * A session already held in the current (unflushed) batch reuses the retention resolved for it
 * earlier; only the rest are resolved via the retention service (batched Redis MGET + a deduped
 * team service fallback). Keys on the `session_id` header, which {@link createValidateSessionReplayHeadersStep}
 * guarantees is present. A session whose retention can't be resolved because its team is unknown or
 * deleted is dropped; a corrupt/invalid stored value instead throws (crashes) rather than recording
 * against a wrong retention. A transient failure (e.g. Redis) is thrown by the service so the
 * pipeline's retry wrapper can re-run the step. A dropped message still commits its offset — the
 * drop result flows out of the pipeline as a record-phase result carrying its source message, which
 * the consumer's offset tracking picks up on the next drain.
 */
export function createResolveRetentionStep<
    T extends { team: TeamForReplay; headers: SessionReplayHeaders } & SessionBatchContext,
>(retentionService: RetentionService): BatchProcessingStep<T, T & { retentionPeriod: RetentionPeriod }> {
    return async function resolveRetentionStep(values) {
        // Reuse retention already resolved for sessions still in this cycle's (unflushed) recorder;
        // resolve the rest. The recorder is minted per cycle and carried on every element.
        // Collecting into a SessionSet dedupes repeated sessions so each is looked up only once.
        const batchRetentions = values.map((value) =>
            value.sessionBatchRecorder.getRetention(value.team.teamId, value.headers.session_id)
        )
        const toResolve = new SessionSet()
        values.forEach((value, index) => {
            if (batchRetentions[index] === undefined) {
                toResolve.add(value.team.teamId, value.headers.session_id)
            }
        })
        const resolutions = await retentionService.resolveSessionRetentions(toResolve)

        return values.map((value, index) => {
            const cached = batchRetentions[index]
            if (cached !== undefined) {
                return ok({ ...value, retentionPeriod: cached })
            }
            const resolution = resolutions.get(value.team.teamId, value.headers.session_id)!
            if (resolution.resolved) {
                return ok({ ...value, retentionPeriod: resolution.retentionPeriod })
            }
            SessionBatchMetrics.incrementSessionsDroppedMissingRetention()
            logger.warn('🔁', 'session_replay_retention_unresolved_dropping_session', {
                sessionId: value.headers.session_id,
                teamId: value.team.teamId,
            })
            return drop('retention_unresolved')
        })
    }
}

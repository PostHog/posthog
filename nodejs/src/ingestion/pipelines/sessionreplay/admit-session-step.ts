import { logger } from '~/common/utils/logger'
import { drop, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ExtractSessionDataStepOutput } from '~/ingestion/pipelines/sessionreplay/extract-session-data-step'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { ValueMatcher } from '~/types'

export interface AdmitSessionStepInput extends SessionBatchContext, ExtractSessionDataStepOutput {
    parsedMessage: ParsedMessageData
}

export interface AdmitSessionStepConfig {
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Creates a step that asks the batch recorder to admit the message into the session batch,
 * enforcing the per-session-per-batch rate limit and the team/key consistency checks, and creating
 * the session's batch entry on first sight. A refused message is dropped here, so the downstream
 * record steps only ever see admitted messages.
 */
export function createAdmitSessionStep<T extends AdmitSessionStepInput>(
    config: AdmitSessionStepConfig
): ProcessingStep<T, T> {
    const { isDebugLoggingEnabled } = config

    return function admitSessionStep(input) {
        const { session, data, parsedMessage, sessionBatchRecorder } = input

        // Reset revoked sessions counter once we're consuming
        SessionRecordingIngesterMetrics.resetSessionsRevoked()

        if (isDebugLoggingEnabled(session.partition)) {
            logger.debug('🔄', 'processing_session_recording', {
                partition: parsedMessage.metadata.partition,
                offset: parsedMessage.metadata.offset,
                distinct_id: parsedMessage.distinct_id,
                session_id: parsedMessage.session_id,
                raw_size: parsedMessage.metadata.rawSize,
            })
            logger.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - consuming event', {
                ...parsedMessage.metadata,
                team_id: session.teamId,
                session_id: session.sessionId,
            })
        }

        SessionRecordingIngesterMetrics.observeSessionInfo(parsedMessage.metadata.rawSize)

        const verdict = sessionBatchRecorder.admit(session, data.eventCount)
        if (verdict !== 'admitted') {
            return Promise.resolve(drop(verdict))
        }
        return Promise.resolve(ok(input))
    }
}

import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ExtractConsoleLogsStepOutput } from '~/ingestion/pipelines/sessionreplay/extract-console-logs-step'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { SerializeSessionStepOutput } from '~/ingestion/pipelines/sessionreplay/serialize-session-step'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { ValueMatcher } from '~/types'

export interface RecordSessionEventStepInput
    extends SessionBatchContext,
        SerializeSessionStepOutput,
        ExtractConsoleLogsStepOutput {
    parsedMessage: ParsedMessageData
}

export interface RecordSessionEventStepConfig {
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Creates a step that aggregates a message's precomputed record data — derived by the serialize
 * and extract-console-logs steps — into the session batch: session data first, then, if the
 * recorder accepted the message, its console logs and features. The parsed message still feeds
 * feature extraction, which is a sequential state machine across a session's messages and can't
 * be precomputed.
 *
 * Metrics (tracked via TopHog wrapper in the pipeline):
 * - message_size_by_session_id: Sum of raw message sizes per session
 * - consume_time_ms_by_session_id: Time spent recording each message
 */
export function createRecordSessionEventStep<T extends RecordSessionEventStepInput>(
    config: RecordSessionEventStepConfig
): ProcessingStep<T, T> {
    const { isDebugLoggingEnabled } = config

    return async function recordSessionEventStep(input) {
        const { session, data, logs, parsedMessage, sessionBatchRecorder } = input

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

        // Aggregate into the batch's recorder, carried on the element by the pipeline's beforeBatch.
        const { accepted } = sessionBatchRecorder.recordSessionData(session, data)
        if (accepted) {
            await sessionBatchRecorder.recordSessionLogs(session, logs)
            sessionBatchRecorder.recordSessionFeatures(session, parsedMessage)
        }

        return ok(input)
    }
}

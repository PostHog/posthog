import { logger } from '~/common/utils/logger'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ExtractConsoleLogsStepOutput } from '~/ingestion/pipelines/sessionreplay/extract-console-logs-step'
import { ExtractSessionDataStepOutput } from '~/ingestion/pipelines/sessionreplay/extract-session-data-step'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { ValueMatcher } from '~/types'

export interface RecordSessionEventStepInput
    extends SessionBatchContext,
        ExtractSessionDataStepOutput,
        ExtractConsoleLogsStepOutput {
    parsedMessage: ParsedMessageData
}

export interface RecordSessionEventStepConfig {
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Creates a step that aggregates a message's precomputed record data — derived by the
 * extract-session-data and extract-console-logs steps — into the session batch. The parsed
 * message still feeds feature extraction, which is a sequential state machine across a session's
 * messages and can't be precomputed.
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
        await sessionBatchRecorder.record(session, data, logs, parsedMessage)

        return ok(input)
    }
}

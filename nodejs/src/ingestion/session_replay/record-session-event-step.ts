import { ParsedMessageData } from '../../session-recording/kafka/types'
import { SessionRecordingIngesterMetrics } from '../../session-recording/metrics'
import { SessionBatchManager } from '../../session-recording/sessions/session-batch-manager'
import { MessageWithTeam, TeamForReplay } from '../../session-recording/teams/types'
import { ValueMatcher } from '../../types'
import { logger } from '../../utils/logger'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface RecordSessionEventStepInput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
}

export interface RecordSessionEventStepConfig {
    sessionBatchManager: SessionBatchManager
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Creates a step that records parsed session event messages to the session batch.
 * This is a side-effect step that writes to the session batch recorder.
 *
 * Metrics (tracked via TopHog wrapper in the pipeline):
 * - message_size_by_session_id: Sum of raw message sizes per session
 * - consume_time_ms_by_session_id: Time spent recording each message
 */
export function createRecordSessionEventStep<T extends RecordSessionEventStepInput>(
    config: RecordSessionEventStepConfig
): ProcessingStep<T, T> {
    const { sessionBatchManager, isDebugLoggingEnabled } = config

    return async function recordSessionEventStep(input) {
        const { team, parsedMessage } = input

        // Reset revoked sessions counter once we're consuming
        SessionRecordingIngesterMetrics.resetSessionsRevoked()

        const { partition } = parsedMessage.metadata
        if (isDebugLoggingEnabled(partition)) {
            logger.debug('🔄', 'processing_session_recording', {
                partition: parsedMessage.metadata.partition,
                offset: parsedMessage.metadata.offset,
                distinct_id: parsedMessage.distinct_id,
                session_id: parsedMessage.session_id,
                raw_size: parsedMessage.metadata.rawSize,
            })
            logger.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - consuming event', {
                ...parsedMessage.metadata,
                team_id: team.teamId,
                session_id: parsedMessage.session_id,
            })
        }

        SessionRecordingIngesterMetrics.observeSessionInfo(parsedMessage.metadata.rawSize)

        // Record to the session batch
        const batch = sessionBatchManager.getCurrentBatch()
        const messageWithTeam: MessageWithTeam = { team, message: parsedMessage }
        await batch.record(messageWithTeam)

        return ok(input)
    }
}

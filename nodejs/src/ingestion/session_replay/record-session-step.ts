import { ParsedMessageData } from '../../session-recording/kafka/types'
import { SessionRecordingIngesterMetrics } from '../../session-recording/metrics'
import { SessionBatchManager } from '../../session-recording/sessions/session-batch-manager'
import { MessageWithTeam, TeamForReplay } from '../../session-recording/teams/types'
import { TopTracker } from '../../session-recording/top-tracker'
import { ValueMatcher } from '../../types'
import { logger } from '../../utils/logger'
import { ok } from '../pipelines/results'
import { ProcessingStep } from '../pipelines/steps'

export interface RecordSessionStepInput {
    team: TeamForReplay
    parsedMessage: ParsedMessageData
}

export interface RecordSessionStepConfig {
    sessionBatchManager: SessionBatchManager
    topTracker: TopTracker
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Creates a step that records parsed session messages to the session batch.
 * This is a side-effect step that writes to the session batch recorder.
 */
export function createRecordSessionStep<T extends RecordSessionStepInput>(
    config: RecordSessionStepConfig
): ProcessingStep<T, T> {
    const { sessionBatchManager, topTracker, isDebugLoggingEnabled } = config

    return async function recordSessionStep(input) {
        const consumeStartTime = performance.now()
        const { team, parsedMessage } = input

        // Reset revoked sessions counter once we're consuming
        SessionRecordingIngesterMetrics.resetSessionsRevoked()

        const debugEnabled = isDebugLoggingEnabled(parsedMessage.metadata.partition)
        if (debugEnabled) {
            logger.debug('🔄', 'processing_session_recording', {
                partition: parsedMessage.metadata.partition,
                offset: parsedMessage.metadata.offset,
                distinct_id: parsedMessage.distinct_id,
                session_id: parsedMessage.session_id,
                raw_size: parsedMessage.metadata.rawSize,
            })
        }

        const { partition } = parsedMessage.metadata
        const isDebug = isDebugLoggingEnabled(partition)
        if (isDebug) {
            logger.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - consuming event', {
                ...parsedMessage.metadata,
                team_id: team.teamId,
                session_id: parsedMessage.session_id,
            })
        }

        SessionRecordingIngesterMetrics.observeSessionInfo(parsedMessage.metadata.rawSize)

        // Track message size per session_id
        const trackingKey = `token:${parsedMessage.token ?? 'unknown'}:session_id:${parsedMessage.session_id}`
        topTracker.increment('message_size_by_session_id', trackingKey, parsedMessage.metadata.rawSize)

        // Record to the session batch
        const batch = sessionBatchManager.getCurrentBatch()
        const messageWithTeam: MessageWithTeam = { team, message: parsedMessage }
        await batch.record(messageWithTeam)

        // Track consume time per session_id
        const consumeEndTime = performance.now()
        const consumeDurationMs = consumeEndTime - consumeStartTime
        topTracker.increment('consume_time_ms_by_session_id', trackingKey, consumeDurationMs)

        return ok(input)
    }
}

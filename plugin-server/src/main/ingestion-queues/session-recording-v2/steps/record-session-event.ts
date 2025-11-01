import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { ProcessingStep } from '../../../../ingestion/pipelines/steps'
import { ValueMatcher } from '../../../../types'
import { logger } from '../../../../utils/logger'
import { ParsedMessageData } from '../kafka/types'
import { SessionRecordingIngesterMetrics } from '../metrics'
import { SessionBatchRecorder } from '../sessions/session-batch-recorder'
import { MessageWithTeam, TeamForReplay } from '../teams/types'

type Input = {
    parsedMessage: ParsedMessageData
    team: TeamForReplay
    batchRecorder: SessionBatchRecorder
}

export function createRecordSessionEventStep<T extends Input>(
    isDebugLoggingEnabled: ValueMatcher<number>
): ProcessingStep<T, void> {
    return async function recordSessionEventStep(input: T): Promise<PipelineResult<void>> {
        // Reset sessions revoked metric
        // We have to reset this counter once we're consuming messages since then we know we're not re-balancing
        // Otherwise the consumer continues to report however many sessions were revoked at the last re-balance forever
        SessionRecordingIngesterMetrics.resetSessionsRevoked()

        const { parsedMessage, team, batchRecorder } = input
        const debugEnabled = isDebugLoggingEnabled(parsedMessage.metadata.partition)

        // Log debug info if enabled
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

        // Observe session info metrics
        SessionRecordingIngesterMetrics.observeSessionInfo(parsedMessage.metadata.rawSize)

        // Record to batch using batch recorder
        const messageWithTeam: MessageWithTeam = {
            team,
            message: parsedMessage,
        }
        await batchRecorder.record(messageWithTeam)

        return ok(undefined)
    }
}

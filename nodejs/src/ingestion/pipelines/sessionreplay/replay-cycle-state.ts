/**
 * The session replay cycle state and how it is managed: what the accumulating pipeline's cycle
 * accumulates (the recorder plus the offsets to commit), how a fresh state is minted, and how
 * every drained result folds into it.
 */
import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { logger } from '~/common/utils/logger'
import { CycleReducer } from '~/ingestion/framework/accumulating-pipeline'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { isOkResult } from '~/ingestion/framework/results'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { SessionBatchManager } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-manager'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { MessageWithTeam } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { ValueMatcher } from '~/types'

import { SessionReplayPipelineOutput } from './pipeline-types'

/**
 * The cycle state — the one accumulator the reducer folds every drained result into: the recorder
 * that OK results are recorded into, plus the highest offset seen per partition. Every message's
 * offset counts — recorded, dropped, or DLQ'd — so the flush's commit advances past dropped
 * messages too.
 */
export interface ReplayCycleState {
    sessionBatchRecorder: SessionBatchRecorder
    offsets: Map<number, number>
}

/** The accumulating pipeline's onNewCycle: mints a fresh recorder from the manager plus empty offsets. */
export function createReplayOnNewCycle(sessionBatchManager: SessionBatchManager): () => ReplayCycleState {
    return () => ({ sessionBatchRecorder: sessionBatchManager.createBatch(), offsets: new Map() })
}

export interface ReplayCycleReducerConfig {
    /** TopHog registry for the per-session record metrics. */
    topHog: TopHogRegistry
    /** Debug logging matcher for partition-based debugging. */
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * The cycle reducer: folds one drained result into the cycle state, exactly once per message.
 * Every message's offset counts — recorded, dropped, or DLQ'd — so the flush's commit advances
 * past every message the cycle covers; OK results are additionally recorded into the state's
 * batch recorder, using the retention and encryption key the pipeline resolved.
 */
export function createReplayCycleReducer(
    config: ReplayCycleReducerConfig
): CycleReducer<ReplayCycleState, SessionReplayPipelineOutput, { message: Message }, OverflowOutput> {
    const { topHog, isDebugLoggingEnabled } = config
    const messageSize = topHog.registerSum('message_size_by_session_id')
    const consumeTime = topHog.registerSum('consume_time_ms_by_session_id')

    return async function reduceReplayCycleState(state, element) {
        const { partition, offset } = element.context.message
        const current = state.offsets.get(partition)
        if (current === undefined || offset > current) {
            state.offsets.set(partition, offset)
        }

        if (!isOkResult(element.result)) {
            return state
        }
        const { team, parsedMessage, retentionPeriod, sessionKey } = element.result.value

        // Reset revoked sessions counter once we're consuming
        SessionRecordingIngesterMetrics.resetSessionsRevoked()
        if (isDebugLoggingEnabled(parsedMessage.metadata.partition)) {
            logger.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - recording event', {
                ...parsedMessage.metadata,
                team_id: team.teamId,
                session_id: parsedMessage.session_id,
            })
        }
        SessionRecordingIngesterMetrics.observeSessionInfo(parsedMessage.metadata.rawSize)

        const labels = { token: parsedMessage.token ?? 'unknown', session_id: parsedMessage.session_id }
        messageSize.record(labels, parsedMessage.metadata.rawSize)
        const start = performance.now()
        const messageWithTeam: MessageWithTeam = { team, message: parsedMessage }
        await state.sessionBatchRecorder.record(messageWithTeam, retentionPeriod, sessionKey)
        consumeTime.record(labels, performance.now() - start)

        return state
    }
}

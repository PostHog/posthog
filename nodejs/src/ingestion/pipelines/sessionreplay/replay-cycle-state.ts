/**
 * The session replay cycle state and the reduce steps that manage it: what the accumulating
 * pipeline's cycle accumulates (the recorder plus the offsets to commit), how a fresh state is
 * minted, and how every drained result folds into it.
 */
import { Message } from 'node-rdkafka'

import { OverflowOutput } from '~/common/outputs'
import { logger } from '~/common/utils/logger'
import { ReduceInput } from '~/ingestion/framework/accumulating-pipeline'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { isOkResult, ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionRecordingIngesterMetrics } from '~/ingestion/pipelines/sessionreplay/metrics'
import { SessionBatchManager } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-manager'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { ValueMatcher } from '~/types'

import { SessionReplayPipelineOutput } from './pipeline-types'

/**
 * The cycle state — the one accumulator the reduce pipeline folds every drained result into: the
 * recorder that OK results are recorded into, plus the highest offset seen per partition. Every
 * message's offset counts — recorded, dropped, or DLQ'd — so the flush's commit advances past
 * dropped messages too.
 */
export interface ReplayCycleState {
    sessionBatchRecorder: SessionBatchRecorder
    offsets: Map<number, number>
}

/** What the replay reduce pipeline processes: the cycle state paired with one drained result. */
export type ReplayReduceInput = ReduceInput<
    ReplayCycleState,
    SessionReplayPipelineOutput,
    { message: Message },
    OverflowOutput
>

/** The accumulating pipeline's onNewCycle: mints a fresh recorder from the manager plus empty offsets. */
export function createReplayOnNewCycle(sessionBatchManager: SessionBatchManager): () => ReplayCycleState {
    return () => ({ sessionBatchRecorder: sessionBatchManager.createBatch(), offsets: new Map() })
}

/**
 * Reduce step: folds the source partition and offset of EVERY drained result — recorded, dropped,
 * or DLQ'd — into the state, so the flush's commit advances past every message the cycle covers.
 */
export function createFoldOffsetsStep(): ProcessingStep<ReplayReduceInput, ReplayReduceInput> {
    return function foldOffsetsStep(input) {
        const { partition, offset } = input.element.context.message
        const current = input.state.offsets.get(partition)
        if (current === undefined || offset > current) {
            input.state.offsets.set(partition, offset)
        }
        return Promise.resolve(ok(input))
    }
}

export interface RecordToStateStepConfig {
    /** TopHog registry for the per-session record metrics. */
    topHog: TopHogRegistry
    /** Debug logging matcher for partition-based debugging. */
    isDebugLoggingEnabled: ValueMatcher<number>
}

/**
 * Reduce step (aggregation): folds an OK result's precomputed record data — derived by the inner
 * pipeline's serialize step — into the state's batch recorder: session data first, then, if the
 * recorder accepted the message, its console logs and features. Non-OK results pass straight
 * through to the state. The reduce pipeline's last step, so it returns the state.
 */
export function createRecordToStateStep(
    config: RecordToStateStepConfig
): ProcessingStep<ReplayReduceInput, ReplayCycleState> {
    const { topHog, isDebugLoggingEnabled } = config
    const messageSize = topHog.registerSum('message_size_by_session_id')
    const consumeTime = topHog.registerSum('consume_time_ms_by_session_id')

    return async function recordToStateStep(input) {
        const { state, element } = input
        if (!isOkResult(element.result)) {
            return ok(state)
        }
        const { session, data, logs, parsedMessage } = element.result.value

        // Reset revoked sessions counter once we're consuming
        SessionRecordingIngesterMetrics.resetSessionsRevoked()
        if (isDebugLoggingEnabled(session.partition)) {
            logger.info('🔁', '[blob_ingester_consumer_v2] - [PARTITION DEBUG] - recording event', {
                ...parsedMessage.metadata,
                team_id: session.teamId,
                session_id: session.sessionId,
            })
        }
        SessionRecordingIngesterMetrics.observeSessionInfo(parsedMessage.metadata.rawSize)

        const labels = { token: parsedMessage.token ?? 'unknown', session_id: session.sessionId }
        messageSize.record(labels, parsedMessage.metadata.rawSize)
        const start = performance.now()
        const { accepted } = state.sessionBatchRecorder.recordSessionData(session, data)
        if (accepted) {
            await state.sessionBatchRecorder.recordSessionLogs(session, logs)
            state.sessionBatchRecorder.recordSessionFeatures(session, parsedMessage)
        }
        consumeTime.record(labels, performance.now() - start)

        return ok(state)
    }
}

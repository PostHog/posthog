import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { SessionRef } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'

export interface RecordSessionFeaturesStepInput extends SessionBatchContext {
    session: SessionRef
    parsedMessage: ParsedMessageData
}

/**
 * Creates a step that feeds the message's parsed events into its session's feature extraction.
 * Takes the parsed message rather than precomputed data: feature extraction is a sequential state
 * machine across a session's messages and can't be precomputed per message. Runs only on admitted
 * messages — the admit step drops the rest.
 */
export function createRecordSessionFeaturesStep<T extends RecordSessionFeaturesStepInput>(): ProcessingStep<T, T> {
    return function recordSessionFeaturesStep(input) {
        input.sessionBatchRecorder.recordSessionFeatures(input.session, input.parsedMessage)
        return Promise.resolve(ok(input))
    }
}

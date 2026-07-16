import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { AdmitSessionStepOutput } from '~/ingestion/pipelines/sessionreplay/admit-session-step'
import { ParsedMessageData } from '~/ingestion/pipelines/sessionreplay/kafka/types'

export interface RecordSessionFeaturesStepInput extends AdmitSessionStepOutput {
    parsedMessage: ParsedMessageData
}

/**
 * Creates a step that feeds the message's parsed events into its session's feature extraction,
 * through the record handle the admit step stamped on the element. Takes the parsed message rather
 * than precomputed data: feature extraction is a sequential state machine across a session's
 * messages and can't be precomputed per message.
 */
export function createRecordSessionFeaturesStep<T extends RecordSessionFeaturesStepInput>(): ProcessingStep<T, T> {
    return function recordSessionFeaturesStep(input) {
        input.admittedSession.recordSessionFeatures(input.parsedMessage)
        return Promise.resolve(ok(input))
    }
}

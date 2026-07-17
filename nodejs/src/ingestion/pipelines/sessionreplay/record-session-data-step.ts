import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { AdmitSessionStepOutput } from '~/ingestion/pipelines/sessionreplay/admit-session-step'
import { SerializedSessionData } from '~/ingestion/pipelines/sessionreplay/sessions/snappy-session-recorder'

export interface RecordSessionDataStepInput extends AdmitSessionStepOutput {
    data: SerializedSessionData
}

/**
 * Creates a step that folds the message's extracted session data into its session block in the
 * batch, through the record handle the admit step stamped on the element.
 */
export function createRecordSessionDataStep<T extends RecordSessionDataStepInput>(): ProcessingStep<T, T> {
    return function recordSessionDataStep(input) {
        input.admittedSession.recordSessionData(input.data)
        return Promise.resolve(ok(input))
    }
}

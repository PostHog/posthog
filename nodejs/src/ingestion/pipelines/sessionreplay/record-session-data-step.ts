import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ExtractSessionDataStepOutput } from '~/ingestion/pipelines/sessionreplay/extract-session-data-step'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'

export interface RecordSessionDataStepInput extends SessionBatchContext, ExtractSessionDataStepOutput {}

/**
 * Creates a step that folds the message's extracted session data into its session block in the
 * batch. Runs only on admitted messages — the admit step drops the rest.
 */
export function createRecordSessionDataStep<T extends RecordSessionDataStepInput>(): ProcessingStep<T, T> {
    return function recordSessionDataStep(input) {
        input.sessionBatchRecorder.recordSessionData(input.session, input.data)
        return Promise.resolve(ok(input))
    }
}

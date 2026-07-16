import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { ExtractConsoleLogsStepOutput } from '~/ingestion/pipelines/sessionreplay/extract-console-logs-step'
import { SessionBatchContext } from '~/ingestion/pipelines/sessionreplay/session-batch-context'
import { SessionRef } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'

export interface RecordSessionLogsStepInput extends SessionBatchContext, ExtractConsoleLogsStepOutput {
    session: SessionRef
}

/**
 * Creates a step that folds the message's extracted console logs into its session in the batch.
 * Runs only on admitted messages — the admit step drops the rest.
 */
export function createRecordSessionLogsStep<T extends RecordSessionLogsStepInput>(): ProcessingStep<T, T> {
    return async function recordSessionLogsStep(input) {
        await input.sessionBatchRecorder.recordSessionLogs(input.session, input.logs)
        return ok(input)
    }
}

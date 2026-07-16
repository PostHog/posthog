import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { AdmitSessionStepOutput } from '~/ingestion/pipelines/sessionreplay/admit-session-step'
import { ExtractConsoleLogsStepOutput } from '~/ingestion/pipelines/sessionreplay/extract-console-logs-step'

export interface RecordSessionLogsStepInput extends AdmitSessionStepOutput, ExtractConsoleLogsStepOutput {}

/**
 * Creates a step that folds the message's extracted console logs into its session in the batch,
 * through the record handle the admit step stamped on the element.
 */
export function createRecordSessionLogsStep<T extends RecordSessionLogsStepInput>(): ProcessingStep<T, T> {
    return async function recordSessionLogsStep(input) {
        await input.admittedSession.recordSessionLogs(input.logs)
        return ok(input)
    }
}

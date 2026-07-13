import { BeforeBatchInput, BeforeBatchOutput } from '~/ingestion/framework/batching-pipeline'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { SessionBatchContext } from './session-batch-context'
import { SessionBatchManager } from './sessions/session-batch-manager'

/**
 * beforeBatch hook for the session replay pipeline: tags the manager's current recorder onto the
 * batch context, which the batching pipeline merges into every element ({@link SessionBatchContext}).
 * Steps that fold into or read from the batch take the recorder off their element, so they stay
 * decoupled from the manager and its current-batch state.
 */
export function createAttachSessionBatchStep<TInput, CInput>(
    sessionBatchManager: SessionBatchManager
): ProcessingStep<BeforeBatchInput<TInput, CInput>, BeforeBatchOutput<TInput, CInput, SessionBatchContext>> {
    return function attachSessionBatchStep(input) {
        return Promise.resolve(
            ok({
                elements: input.elements,
                batchContext: { ...input.batchContext, sessionBatchRecorder: sessionBatchManager.getCurrentBatch() },
            })
        )
    }
}

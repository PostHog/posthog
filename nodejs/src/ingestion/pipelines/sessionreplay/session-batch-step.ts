import { BeforeAccumulationInput, BeforeAccumulationOutput } from '~/ingestion/framework/accumulating-pipeline'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { SessionBatchContext } from './session-batch-context'
import { SessionBatchManager } from './sessions/session-batch-manager'

/**
 * The accumulating pipeline's beforeBatch step: mints a fresh recorder from the manager for the next
 * accumulation cycle and hands it to the pipeline as the batch context.
 */
export function createCreateSessionBatchStep(
    sessionBatchManager: SessionBatchManager
): ProcessingStep<BeforeAccumulationInput, BeforeAccumulationOutput<SessionBatchContext>> {
    return function createSessionBatchStep(batchContext) {
        return Promise.resolve(
            ok({ batchContext: { ...batchContext, sessionBatchRecorder: sessionBatchManager.createBatch() } })
        )
    }
}

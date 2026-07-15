import { BeforeCycleInput, BeforeCycleOutput } from '~/ingestion/framework/accumulating-pipeline'
import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { SessionBatchContext } from './session-batch-context'
import { SessionBatchManager } from './sessions/session-batch-manager'

/**
 * The accumulating pipeline's beforeCycle step: mints a fresh recorder from the manager for the
 * next accumulation cycle and hands it to the pipeline as the cycle context.
 */
export function createMintSessionBatchStep(
    sessionBatchManager: SessionBatchManager
): ProcessingStep<BeforeCycleInput, BeforeCycleOutput<SessionBatchContext>> {
    return function mintSessionBatchStep(input) {
        return Promise.resolve(
            ok({ cycleContext: { ...input, sessionBatchRecorder: sessionBatchManager.createBatch() } })
        )
    }
}

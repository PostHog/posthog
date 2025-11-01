import { BatchProcessingStep } from '../../../../ingestion/pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { SessionBatchManager } from '../sessions/session-batch-manager'

/**
 * Maybe flush batch step
 *
 * This is a batch-level step that checks if the session batch manager should flush,
 * and if so, flushes all pending batches to storage.
 *
 * This step passes through its input unchanged and should be called after all messages
 * have been processed and side effects handled.
 */
export function createMaybeFlushBatchStep<T>(sessionBatchManager: SessionBatchManager): BatchProcessingStep<T, T> {
    return async function maybeFlushBatchStep(batch: T[]): Promise<PipelineResult<T>[]> {
        // Check if we should flush
        if (sessionBatchManager.shouldFlush()) {
            await sessionBatchManager.flush()
        }

        // Return input unchanged
        return batch.map((item) => ok(item))
    }
}

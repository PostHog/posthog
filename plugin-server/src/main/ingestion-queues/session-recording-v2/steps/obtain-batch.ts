import { BatchProcessingStep } from '../../../../ingestion/pipelines/base-batch-pipeline'
import { PipelineResult, ok } from '../../../../ingestion/pipelines/results'
import { SessionBatchManager } from '../sessions/session-batch-manager'
import { SessionBatchRecorder } from '../sessions/session-batch-recorder'

type Output = { batchRecorder: SessionBatchRecorder }

export function createObtainBatchStep<T>(sessionBatchManager: SessionBatchManager): BatchProcessingStep<T, T & Output> {
    return function obtainBatchStep(batch: T[]): Promise<PipelineResult<T & Output>[]> {
        // Get the current batch recorder once for all messages
        const batchRecorder = sessionBatchManager.getCurrentBatch()

        // Attach the batch recorder to each message
        const results = batch.map((input) =>
            ok({
                ...input,
                batchRecorder,
            })
        )

        return Promise.resolve(results)
    }
}

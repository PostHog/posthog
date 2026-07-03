import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { SessionBatchMetrics } from './sessions/metrics'

/**
 * Flush step: record the flush counters (batches/sessions/events/bytes) from the write step's block
 * metadata. Runs after the commit step, so a batch that fails to commit (and will be reprocessed)
 * isn't counted here — avoiding the double-count that recording before commit would cause.
 */
export function createRecordMetricsStep(): ProcessingStep<SessionBlockMetadata[], SessionBlockMetadata[]> {
    return function recordMetricsStep(blockMetadata) {
        SessionBatchMetrics.recordFlushedBatch(blockMetadata)
        return Promise.resolve(ok(blockMetadata))
    }
}

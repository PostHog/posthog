import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { SessionBatchMetrics } from './sessions/metrics'

/**
 * Flush step: record the flush counters (batches/sessions/events/bytes) from the write step's block
 * metadata, read off the threaded flush value. Runs after the commit step, so a cycle that fails to
 * commit (and will be reprocessed) isn't counted here — avoiding the double-count that recording
 * before commit would cause. Passes the value through unchanged.
 */
export function createRecordMetricsStep<T extends { blockMetadata: SessionBlockMetadata[] }>(): ProcessingStep<T, T> {
    return function recordMetricsStep(input) {
        SessionBatchMetrics.recordFlushedBatch(input.blockMetadata)
        return Promise.resolve(ok(input))
    }
}

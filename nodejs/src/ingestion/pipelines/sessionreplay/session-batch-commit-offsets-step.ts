import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'

import { KafkaOffsetManager } from './kafka/offset-manager'

/**
 * Flush step: commit the Kafka offsets tracked so far. Runs after the write step, so offsets are
 * only committed once the batch is durably in storage. A commit failure throws and fails the flush,
 * so the batch is reprocessed (and the downstream metrics step doesn't run). Passes its value
 * through unchanged.
 */
export function createCommitOffsetsStep<T>(offsetManager: KafkaOffsetManager): ProcessingStep<T, T> {
    return async function commitOffsetsStep(value) {
        await offsetManager.commit()
        return ok(value)
    }
}

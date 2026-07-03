import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { SessionBatchContext } from './session-batch-context'

/**
 * Flush step: write the accumulated batch to storage. Each session's retention was resolved and
 * stored on the recorder at record time, so nothing here touches Redis; a later flush step commits
 * offsets on the written result, so nothing here touches Kafka offsets either.
 *
 * Reads the recorder off the flush input's batch context and threads the written block metadata onto
 * the input, so the accumulated elements and batch context stay available to the downstream steps.
 * The input is generic so it only requires the field it reads.
 */
export function createWriteStep<T extends { batchContext: SessionBatchContext }>(): ProcessingStep<
    T,
    T & { blockMetadata: SessionBlockMetadata[] }
> {
    return async function writeStep(input) {
        const blockMetadata = await input.batchContext.sessionBatchRecorder.flush()
        return ok({ ...input, blockMetadata })
    }
}

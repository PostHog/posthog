import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { ReplayCycleState } from './replay-cycle-state'

/**
 * Flush step: write the accumulated batch to storage. Each session's retention was resolved and
 * stored on the recorder at record time, so nothing here touches Redis; the commit step that
 * follows commits the offsets on the written result, so nothing here touches Kafka offsets either.
 *
 * Reads the recorder off the cycle state and threads the written block metadata onto the input, so
 * the state stays available to the downstream steps. The input is generic so it only requires the
 * field it reads.
 */
export function createWriteStep<T extends Pick<ReplayCycleState, 'sessionBatchRecorder'>>(): ProcessingStep<
    T,
    T & { blockMetadata: SessionBlockMetadata[] }
> {
    return async function writeStep(input) {
        const blockMetadata = await input.sessionBatchRecorder.flush()
        return ok({ ...input, blockMetadata })
    }
}

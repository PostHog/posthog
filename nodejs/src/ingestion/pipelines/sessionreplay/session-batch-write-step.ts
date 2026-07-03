import { ok } from '~/ingestion/framework/results'
import { ProcessingStep } from '~/ingestion/framework/steps'
import { SessionBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { SessionBatchContext } from './session-batch-context'

/**
 * Flush step: write the accumulated batch to storage. Each session's retention was resolved and
 * stored on the recorder at record time, so nothing here touches Redis; a later flush step commits
 * offsets on the written result, so nothing here touches Kafka offsets either.
 *
 * Terminal transform (produces block metadata, not an extended context), but its input is generic
 * so it only requires the field it reads — the recorder.
 */
export function createWriteStep<T extends SessionBatchContext>(): ProcessingStep<T, SessionBlockMetadata[]> {
    return async function writeStep(batchContext) {
        return ok(await batchContext.sessionBatchRecorder.flush())
    }
}

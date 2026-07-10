import { SessionBatchRecorder } from './sessions/session-batch-recorder'

/**
 * Batch context attached to every element of a pipeline batch: the recorder the record step folds
 * events into. Tagged on by the pipeline's beforeBatch hook, so steps read the recorder from their
 * element instead of holding a reference to shared batch state.
 *
 * This is a pipeline-level concern (the unit the pipeline threads through its steps), not a recorder
 * concern — the recorder is just what it happens to carry.
 */
export interface SessionBatchContext {
    sessionBatchRecorder: SessionBatchRecorder
}

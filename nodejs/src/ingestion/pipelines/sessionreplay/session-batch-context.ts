import { SessionBatchRecorder } from './sessions/session-batch-recorder'

/**
 * Batch context attached to every element of an accumulation cycle and to the flush units.
 * Carries the recorder that the record step folds into and that the flush step drains.
 *
 * This is a pipeline-level concern (the unit the accumulating pipeline threads through its steps),
 * not a recorder concern — the recorder is just what it happens to carry.
 */
export interface SessionBatchContext {
    sessionBatchRecorder: SessionBatchRecorder
}

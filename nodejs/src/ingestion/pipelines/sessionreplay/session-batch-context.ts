import { SessionBatchRecorder } from './sessions/session-batch-recorder'

/**
 * The recorder a session replay message folds into, carried on every pipeline input element. The layer
 * above the pipeline (the consumer, later the accumulating pipeline) owns the recorder and stamps it on
 * the messages it feeds, so steps read it from their element instead of reaching into shared batch state.
 */
export interface SessionBatchContext {
    sessionBatchRecorder: SessionBatchRecorder
}

/** The part of the recorder that a step can hold outside the batch lock: a retention lookup, not a write. A lane that overlaps batches stamps this, because a flush can replace the recorder at any time. */
export interface RetentionLookupContext {
    sessionBatchRecorder: Pick<SessionBatchRecorder, 'getRetention'>
}

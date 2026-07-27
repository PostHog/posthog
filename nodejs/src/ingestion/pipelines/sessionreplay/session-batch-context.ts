import { SessionBatchRecorder } from './sessions/session-batch-recorder'

/**
 * The recorder a session replay message folds into, carried on every pipeline input element. The layer
 * above the pipeline (the consumer, later the accumulating pipeline) owns the recorder and stamps it on
 * the messages it feeds, so steps read it from their element instead of reaching into shared batch state.
 */
export interface SessionBatchContext {
    sessionBatchRecorder: SessionBatchRecorder
}

/**
 * Replay job — the wrapper job that drives a paginated replay of past hog
 * function or hog flow invocations.
 *
 * Two paths produce these:
 *   1. The Django→Node `/replay` endpoint creates one with `progress.done=false`
 *      and the user's request (either explicit ids or filter).
 *   2. The `CdpReplayWorkerConsumer` dequeues it, runs one page of work, and
 *      either acks (done) or `reschedule({ state })` with updated progress.
 *
 * Why cyclotron-v2 instead of running inline in the API request:
 *   - A by-filter replay can match millions of rows. We can't block on it.
 *   - Resumable: each page persists `progress.cursor` so a crash during a
 *     long replay picks up where it left off rather than from the top.
 *   - Observable: the wrapper row in cyclotron_jobs surfaces in-flight
 *     replays + their progress via the same machinery as every other job.
 */

export const REPLAY_QUEUE_NAME = 'replay'

export type ReplayFunctionKind = 'hog_function' | 'hog_flow'

export type ReplayStatusValue = 'running' | 'succeeded' | 'failed'

export interface ReplayFilter {
    window_start: string
    window_end: string
    status?: ReplayStatusValue[]
    error_kind?: string[]
    max_attempts?: number
    max_count?: number
}

export interface ReplayRequest {
    invocation_ids?: string[]
    filter?: ReplayFilter
}

export interface ReplayCursor {
    scheduled_at: string
    invocation_id: string
}

export interface ReplayJobProgress {
    queued: number
    skipped: number
    /** Keyset cursor for the by-filter mode. Undefined on first page; null when exhausted. */
    cursor?: ReplayCursor | null
    /** For by-IDs mode, the slice of ids not yet processed. */
    remaining_ids?: string[]
    /** True once the worker has processed every page or exhausted max_count. */
    done: boolean
    /** Last error from a page; non-fatal — the next reschedule retries. */
    last_error?: string
}

export interface ReplayJobState {
    function_kind: ReplayFunctionKind
    function_id: string
    request: ReplayRequest
    progress: ReplayJobProgress
}

/** Hard cap on rows fetched per replay page (also caps a by-IDs request slice). */
export const REPLAY_PAGE_SIZE = 200

/** Hard cap on total rows replayed by a single wrapper job. Mirrors HOG_INVOCATION_REPLAY_MAX_COUNT in Django. */
export const HOG_INVOCATION_REPLAY_MAX_COUNT = 1000

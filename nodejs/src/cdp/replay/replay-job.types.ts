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

/**
 * `function_kind` value we stamp on the wrapper row that the worker writes to
 * `hog_invocation_results` to surface a re-run in the Invocations UI alongside
 * the function's normal invocations. Suffixing avoids overloading the existing
 * kind enum and keeps "is this a wrapper?" a trivial check on the frontend.
 */
export type ReplayWrapperFunctionKind = 'hog_function_replay' | 'hog_flow_replay'

export const replayWrapperKindFor = (kind: ReplayFunctionKind): ReplayWrapperFunctionKind =>
    kind === 'hog_flow' ? 'hog_flow_replay' : 'hog_function_replay'

export const isReplayWrapperKind = (kind: string): kind is ReplayWrapperFunctionKind =>
    kind === 'hog_function_replay' || kind === 'hog_flow_replay'

export type ReplayStatusValue = 'running' | 'succeeded' | 'failed'

/**
 * Filter shape for a replay request.
 *
 * `window_start` / `window_end` are REQUIRED — the lifecycle table is
 * partitioned by `toYYYYMMDD(scheduled_at)`, so a query without a time bound
 * scans every partition (up to 30 of them, since the TTL drops parts older
 * than that). The window also caps replay to data that's still resident in the
 * table — older rows are gone via TTL anyway.
 *
 * `invocation_ids` is an OPTIONAL additional restriction. When set, the
 * paginator pulls only those ids within the window — a UI "replay these
 * specific failed runs" affordance. Server-side cap on the list size is
 * enforced via `HOG_INVOCATION_REPLAY_MAX_COUNT`.
 */
export interface ReplayFilter {
    window_start: string
    window_end: string
    status?: ReplayStatusValue[]
    error_kind?: string[]
    max_attempts?: number
    max_count?: number
    invocation_ids?: string[]
}

export interface ReplayRequest {
    filter: ReplayFilter
}

/**
 * Max window the user may pass — matches the ClickHouse TTL on
 * `hog_invocation_results`. Older rows are already gone via part drop.
 */
export const REPLAY_MAX_WINDOW_DAYS = 30

export interface ReplayCursor {
    scheduled_at: string
    invocation_id: string
}

export interface ReplayJobProgress {
    queued: number
    skipped: number
    /** Keyset cursor on (scheduled_at, invocation_id). Undefined on first page; null when exhausted. */
    cursor?: ReplayCursor | null
    /** True once the worker has processed every page or exhausted max_count. */
    done: boolean
    /** Last error from a page; non-fatal — the next reschedule retries. */
    last_error?: string
    /**
     * Number of pages that have committed progress to this job. Bumped per
     * call to `processPage`. Surfaces on the wrapper lifecycle row as `attempts`
     * so the Invocations UI can show "this re-run has worked X pages so far".
     */
    pages_processed?: number
}

export interface ReplayJobState {
    function_kind: ReplayFunctionKind
    function_id: string
    request: ReplayRequest
    progress: ReplayJobProgress
}

/** Hard cap on rows fetched per replay page (also caps a by-IDs request slice). */
export const REPLAY_PAGE_SIZE = 200

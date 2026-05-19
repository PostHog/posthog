/**
 * Rerun job — the wrapper job that drives a paginated rerun of past hog
 * function or hog flow invocations.
 *
 * Two paths produce these:
 *   1. The Django→Node `/rerun` endpoint creates one with `progress.done=false`
 *      and the user's request (either explicit ids or filter).
 *   2. The `CdpRerunWorkerConsumer` dequeues it, runs one page of work, and
 *      either acks (done) or `reschedule({ state })` with updated progress.
 *
 * Why cyclotron-v2 instead of running inline in the API request:
 *   - A by-filter rerun can match millions of rows. We can't block on it.
 *   - Resumable: each page persists `progress.cursor` so a crash during a
 *     long rerun picks up where it left off rather than from the top.
 *   - Observable: the wrapper row in cyclotron_jobs surfaces in-flight
 *     reruns + their progress via the same machinery as every other job.
 */

export const RERUN_QUEUE_NAME = 'rerun'

export type RerunFunctionKind = 'hog_function' | 'hog_flow'

/**
 * `function_kind` value we stamp on the wrapper row that the worker writes to
 * `hog_invocation_results` to surface a re-run in the Invocations UI alongside
 * the function's normal invocations. Suffixing avoids overloading the existing
 * kind enum and keeps "is this a wrapper?" a trivial check on the frontend.
 */
export type RerunWrapperFunctionKind = 'hog_function_rerun' | 'hog_flow_rerun'

export const rerunWrapperKindFor = (kind: RerunFunctionKind): RerunWrapperFunctionKind =>
    kind === 'hog_flow' ? 'hog_flow_rerun' : 'hog_function_rerun'

export const isRerunWrapperKind = (kind: string): kind is RerunWrapperFunctionKind =>
    kind === 'hog_function_rerun' || kind === 'hog_flow_rerun'

export type RerunStatusValue = 'running' | 'succeeded' | 'failed'

/**
 * Filter shape for a rerun request.
 *
 * `window_start` / `window_end` are REQUIRED — the lifecycle table is
 * partitioned by `toYYYYMMDD(scheduled_at)`, so a query without a time bound
 * scans every partition (up to 30 of them, since the TTL drops parts older
 * than that). The window also caps rerun to data that's still resident in the
 * table — older rows are gone via TTL anyway.
 *
 * `invocation_ids` is an OPTIONAL additional restriction. When set, the
 * paginator pulls only those ids within the window — a UI "rerun these
 * specific failed runs" affordance. Server-side cap on the list size is
 * enforced via `HOG_INVOCATION_RERUN_MAX_COUNT`.
 */
export interface RerunFilter {
    window_start: string
    window_end: string
    status?: RerunStatusValue[]
    error_kind?: string[]
    max_attempts?: number
    max_count?: number
    invocation_ids?: string[]
}

export interface RerunRequest {
    filter: RerunFilter
}

/**
 * Max window the user may pass — matches the ClickHouse TTL on
 * `hog_invocation_results`. Older rows are already gone via part drop.
 */
export const RERUN_MAX_WINDOW_DAYS = 30

export interface RerunCursor {
    scheduled_at: string
    invocation_id: string
}

export interface RerunJobProgress {
    queued: number
    skipped: number
    /** Keyset cursor on (scheduled_at, invocation_id). Undefined on first page; null when exhausted. */
    cursor?: RerunCursor | null
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

export interface RerunJobState {
    function_kind: RerunFunctionKind
    function_id: string
    request: RerunRequest
    progress: RerunJobProgress
}

/** Hard cap on rows fetched per rerun page (also caps a by-IDs request slice). */
export const RERUN_PAGE_SIZE = 200

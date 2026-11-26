import posthog from 'posthog-js'

import type { QueryRequest } from '../widgets/chart/vizTypes'
import type { QueryBatchLine } from './queryBatchLines'

export const QUERY_BATCH_TIMING_EVENT = 'dashboard v2 query batch loaded'

export interface TraceContext {
    traceId: string
    traceparent: string
}

function randomHex(bytes: number): string {
    const values = crypto.getRandomValues(new Uint8Array(bytes))
    return Array.from(values, (value) => value.toString(16).padStart(2, '0')).join('')
}

/** A W3C `traceparent` with the sampled flag set. A proxy that keeps it lets the server's spans join this trace. */
export function newTraceContext(): TraceContext {
    let traceId = randomHex(16)
    // An all-zero id is invalid, and the server would then start a trace of its own.
    while (/^0+$/.test(traceId)) {
        traceId = randomHex(16)
    }
    let spanId = randomHex(8)
    while (/^0+$/.test(spanId)) {
        spanId = randomHex(8)
    }
    return { traceId, traceparent: `00-${traceId}-${spanId}-01` }
}

// https://www.w3.org/TR/trace-context-2/#traceresponse-header, in the traceparent format.
const TRACERESPONSE = /^00-([0-9a-f]{32})-[0-9a-f]{16}-[0-9a-f]{2}$/

function percentile(sorted: number[], p: number): number | null {
    if (sorted.length === 0) {
        return null
    }
    return sorted[Math.min(sorted.length - 1, Math.ceil(p * sorted.length) - 1)]
}

const round = (ms: number | null): number | null => (ms === null ? null : Math.round(ms))

/** What a board visit has drawn so far, shared by every batch its runner sends. */
export interface BoardLoad {
    mountedAt: number
    batches: number
    firstResultAt: number | null
    lastResultAt: number | null
}

export function startBoardLoad(now = performance.now()): BoardLoad {
    return { mountedAt: now, batches: 0, firstResultAt: null, lastResultAt: null }
}

/**
 * Times one query batch from the browser: how long its queries waited to be sent, the throttle retries before the
 * stream opened, the first and last line, and how the lines in between were spread. Only counters and a sorted list
 * of arrival times are kept, so a board of a few hundred queries costs a few microseconds per line.
 */
export class QueryBatchTimer {
    readonly trace = newTraceContext()
    private readonly board: BoardLoad
    private readonly queuedAt: number
    private readonly queryCount: number
    private readonly busyRetries: number
    private readonly languages: Record<string, number> = {}
    private startedAt = 0
    private attemptStartedAt = 0
    private throttleRetries = 0
    private headersAt: number | null = null
    private status: number | null = null
    private serverTraceId: string | null = null
    private bytes = 0
    private arrivals: number[] = []
    private errorLines = 0
    private cacheHits = 0
    private staleLines = 0
    private busyLines = 0
    private failure: string | null = null
    private aborted = false

    constructor(board: BoardLoad, requests: { request: QueryRequest; queuedAt: number; retriedBusy?: boolean }[]) {
        this.board = board
        this.queuedAt = Math.min(...requests.map((pending) => pending.queuedAt))
        this.queryCount = requests.length
        this.busyRetries = requests.filter((pending) => pending.retriedBusy).length
        for (const { request } of requests) {
            this.languages[request.query.language] = (this.languages[request.query.language] ?? 0) + 1
        }
    }

    attempt(): void {
        const now = performance.now()
        if (this.startedAt === 0) {
            this.startedAt = now
        } else {
            this.throttleRetries++
        }
        this.attemptStartedAt = now
        this.headersAt = null
        this.status = null
    }

    response(status: number, traceresponse: string | null): void {
        this.headersAt = performance.now()
        this.status = status
        this.serverTraceId = traceresponse?.match(TRACERESPONSE)?.[1] ?? null
    }

    chunk(byteLength: number): void {
        this.bytes += byteLength
    }

    line(line: QueryBatchLine, busy: boolean): void {
        const now = performance.now()
        this.arrivals.push(now - this.attemptStartedAt)
        if (busy) {
            this.busyLines++
            return
        }
        if (line.error) {
            this.errorLines++
            return
        }
        if (line.result?.cache?.hit) {
            this.cacheHits++
        }
        if (line.result?.cache?.stale) {
            this.staleLines++
        }
        this.board.firstResultAt ??= now
        this.board.lastResultAt = now
    }

    get failed(): boolean {
        return this.failure !== null
    }

    fail(error: Error): void {
        this.failure = error.message.slice(0, 200)
        this.aborted = error.name === 'AbortError'
    }

    capture(context: Record<string, unknown>): void {
        const endedAt = performance.now()
        const sorted = [...this.arrivals].sort((a, b) => a - b)
        const fromMount = (at: number | null): number | null => (at === null ? null : at - this.board.mountedAt)
        const batchIndex = this.board.batches++
        posthog.capture(QUERY_BATCH_TIMING_EVENT, {
            ...context,
            // The ingress drops the outbound traceparent, so only the server's own trace id finds its spans.
            trace_id: this.serverTraceId,
            batch_index: batchIndex,
            query_count: this.queryCount,
            query_languages: this.languages,
            language_mix: Object.keys(this.languages).sort().join('+'),
            busy_retried_queries: this.busyRetries,
            throttle_retries: this.throttleRetries,
            status: this.status,
            failed: this.failure !== null,
            error: this.failure,
            aborted: this.aborted,
            // Waits before the stream: the coalesce window, an earlier batch still streaming, and busy retry delays.
            queue_wait_ms: round(this.startedAt - this.queuedAt),
            throttle_wait_ms: round(this.attemptStartedAt - this.startedAt),
            // From the sent request that opened the stream.
            headers_ms: round(this.headersAt === null ? null : this.headersAt - this.attemptStartedAt),
            first_line_ms: round(sorted[0] ?? null),
            line_p50_ms: round(percentile(sorted, 0.5)),
            line_p95_ms: round(percentile(sorted, 0.95)),
            last_line_ms: round(sorted.at(-1) ?? null),
            // From the first attempt, so throttle waits are inside it.
            total_ms: round(endedAt - this.startedAt),
            response_bytes: this.bytes,
            line_count: sorted.length,
            unanswered_queries: this.queryCount - sorted.length,
            error_lines: this.errorLines,
            cache_hits: this.cacheHits,
            stale_lines: this.staleLines,
            busy_lines: this.busyLines,
            since_mount_request_ms: round(this.startedAt - this.board.mountedAt),
            since_mount_first_result_ms: round(fromMount(this.board.firstResultAt)),
            since_mount_last_result_ms: round(fromMount(this.board.lastResultAt)),
        })
    }
}

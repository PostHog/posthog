import { getCookie } from 'lib/api'

import { getDashboardV2QueryBatchCreateUrl } from 'products/dashboards/frontend/generated/api'
import type { QueryBatchRequestApi } from 'products/dashboards/frontend/generated/api.schemas'

import type { TimeRange } from '../dashboard/document/dashboardTypes'
import { type Frame, type QueryBatchLine, readNdjson } from './queryBatchLines'
import { QueryBatchTimer, startBoardLoad } from './queryBatchTiming'
import type { DataFrame, QueryRequest, QueryResult, RunQuery } from './queryTypes'

const NO_ANSWER = 'No answer came back for this query'
// The endpoint answers 429 while this person's earlier batches still hold its slots, which frees up within seconds.
const THROTTLE_RETRY_DELAYS_MS = [1000, 3000, 8000]
// The server frees a finished stream's slot just after its last line, so an immediate retry can still find it held.
const BUSY_RETRY_DELAY_MS = 1000
const MAX_QUERIES_PER_BATCH = 500
// Tiles mount across several ticks, so one tick would split a board into several batches.
const COALESCE_MS = 30
// Each stream holds one of the person's batch slots on the server, so this stays at or below `MAX_BATCHES_PER_USER`.
export const MAX_STREAMS = 3
// `_BUSY` in `products/dashboards/backend/v2/query_batch.py`.
export const BUSY_ERROR = 'Too many dashboards are loading at once. Try again shortly.'

type Pending = {
    request: QueryRequest
    resolve: (result: QueryResult) => void
    reject: (error: Error) => void
    queuedAt: number
    context: Record<string, unknown>
    retriedBusy?: boolean
}

export interface QueryBatchRunnerOptions {
    /** Read when a query is asked, and added to its batch's timing event, such as the tab on screen. */
    context?: () => Record<string, unknown>
}

// TODO(2026-11-25): Send no time when the request has none, once the query batch endpoint accepts that.
// The endpoint requires a time range on every query, so a query with no range of its own here gets this one.
const UNTIL_BATCH_ACCEPTS_NO_TIME: TimeRange = { from: 'now-7d', to: 'now' }

function batchTarget(request: QueryRequest, index: number): QueryBatchRequestApi['queries'][number] {
    const { query, legend } = request
    const time = request.time ?? UNTIL_BATCH_ACCEPTS_NO_TIME
    const refId = String(index)
    const target: QueryBatchRequestApi['queries'][number]['target'] =
        query.language === 'hogql' || query.language === 'promql' || query.language === 'logql'
            ? { refId, language: query.language, query: query.query }
            : {
                  refId,
                  language: 'query',
                  // A `date_from` in its filters, even null, keeps the range saved in the query instead of `time`.
                  query: JSON.stringify(
                      request.time ? query.query : { query: query.query, filters: { date_from: null } }
                  ),
              }
    return {
        target: legend ? { ...target, legend } : target,
        time: { from: time.from, to: time.to },
    }
}

// Calendar dates arrive as midnight UTC, so they are kept as dates rather than read in a timezone a day behind.
function timeLabel(value: unknown, dateOnly: boolean): unknown {
    if (typeof value !== 'number') {
        return value
    }
    const iso = new Date(value).toISOString()
    return dateOnly ? iso.slice(0, 10) : iso
}

export function toDataFrame(frame: Frame): DataFrame {
    return {
        ...(frame.name ? { name: frame.name } : {}),
        fields: frame.fields.map((field) => ({
            name: field.name,
            type: field.type,
            values:
                field.type === 'time'
                    ? field.values.map((value) => timeLabel(value, field.unit === 'date'))
                    : field.values,
            ...(field.type !== 'time' && field.unit ? { unit: field.unit } : {}),
        })),
    }
}

export function resultFromLine(line: QueryBatchLine): QueryResult | Error {
    if (line.error) {
        return new Error(line.error)
    }
    if (!line.result?.frames) {
        return new Error("This query's result can't be drawn as a chart yet")
    }
    const cache = line.result.cache
    return {
        frames: line.result.frames.map(toDataFrame),
        ...(cache?.fetchedAt ? { fetchedAt: cache.fetchedAt } : {}),
        ...(cache?.stale ? { stale: true } : {}),
    }
}

async function postBatch(teamId: number, body: QueryBatchRequestApi, timer: QueryBatchTimer): Promise<Response> {
    for (let attempt = 0; ; attempt++) {
        timer.attempt()
        const response = await fetch(getDashboardV2QueryBatchCreateUrl(String(teamId)), {
            method: 'POST',
            credentials: 'same-origin',
            // No Accept header: DRF negotiates it against JSON renderers before the view streams, so
            // `application/x-ndjson` is refused with a 406.
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('posthog_csrftoken') || '',
                traceparent: timer.trace.traceparent,
            },
            body: JSON.stringify(body),
        })
        timer.response(response.status, response.headers.get('traceresponse'))
        if (response.status !== 429 || attempt >= THROTTLE_RETRY_DELAYS_MS.length) {
            return response
        }
        await new Promise((resolve) => setTimeout(resolve, THROTTLE_RETRY_DELAYS_MS[attempt]))
    }
}

async function runBatch(
    teamId: number,
    batch: Pending[],
    timer: QueryBatchTimer,
    retry: (pending: Pending) => void
): Promise<void> {
    const unanswered = new Map(batch.map((pending, index) => [index, pending]))
    let error = new Error(NO_ANSWER)
    try {
        const response = await postBatch(
            teamId,
            {
                format: 'frames',
                queries: batch.map((pending, index) => batchTarget(pending.request, index)),
            },
            timer
        )
        if (!response.ok || !response.body) {
            error = new Error(`The query batch failed with status ${response.status}`)
        } else {
            await readNdjson(
                response.body,
                (line) => {
                    const pending = unanswered.get(line.i)
                    if (!pending) {
                        return
                    }
                    unanswered.delete(line.i)
                    // Another tab, or a slot not yet freed, held this person's running batches.
                    const busy = line.error === BUSY_ERROR && !pending.retriedBusy
                    timer.line(line, busy)
                    if (busy) {
                        retry({ ...pending, retriedBusy: true, queuedAt: performance.now() })
                        return
                    }
                    const result = resultFromLine(line)
                    if (result instanceof Error) {
                        pending.reject(result)
                    } else {
                        pending.resolve(result)
                    }
                },
                (byteLength) => timer.chunk(byteLength)
            )
        }
    } catch (e) {
        error = e instanceof Error ? e : new Error(String(e))
        timer.fail(error)
    }
    if (!timer.failed && unanswered.size > 0) {
        timer.fail(error)
    }
    // A rejected query leaves the chart cache, so the chart asks again the next time it mounts.
    unanswered.forEach((pending) => pending.reject(error))
}

/**
 * Runs chart queries through `POST dashboard_v2/query_batch/`. The charts that ask within a short window, such as
 * every tile a dashboard mounts, share one stream, and each chart's promise settles as soon as its own line arrives.
 * Up to `MAX_STREAMS` streams run at once, which stays inside the server's per-person shares
 * (`MAX_BATCHES_PER_USER` and `MAX_OPEN_BATCHES_PER_USER`). Charts that ask while every stream is open are sent
 * together once one ends.
 */
export function createQueryBatchRunner(teamId: number, options: QueryBatchRunnerOptions = {}): RunQuery {
    // The scene makes a runner per visit, so its creation stands in for the board mounting.
    const board = startBoardLoad()
    let queued: Pending[] = []
    let timer: ReturnType<typeof setTimeout> | null = null
    let streams = 0
    let nextStream = 0
    const open = new Set<number>()
    // Busy answers wait for every stream that was open when theirs ended, because those streams hold the person's
    // running queries on the server.
    let held: { busy: Pending[]; waitingOn: Set<number>; due: boolean }[] = []

    const flush = (): void => {
        if (timer !== null) {
            clearTimeout(timer)
            timer = null
        }
        held = held.filter((entry) => {
            const ready = entry.due && entry.waitingOn.size === 0
            if (ready) {
                queued.push(...entry.busy)
            }
            return !ready
        })
        while (streams < MAX_STREAMS && queued.length > 0) {
            const batch = queued.slice(0, MAX_QUERIES_PER_BATCH)
            queued = queued.slice(MAX_QUERIES_PER_BATCH)
            streams++
            const id = nextStream++
            open.add(id)
            const busy: Pending[] = []
            const batchTimer = new QueryBatchTimer(board, batch)
            void runBatch(teamId, batch, batchTimer, (pending) => busy.push(pending)).finally(() => {
                try {
                    batchTimer.capture(batch[0].context)
                } catch {
                    // Timing must never hold up the next batch.
                }
                open.delete(id)
                held.forEach((entry) => entry.waitingOn.delete(id))
                const entry = { busy, waitingOn: new Set(open), due: false }
                if (busy.length > 0) {
                    held.push(entry)
                }
                setTimeout(
                    () => {
                        entry.due = true
                        streams--
                        flush()
                    },
                    busy.length > 0 ? BUSY_RETRY_DELAY_MS : 0
                )
            })
        }
    }

    return (request) =>
        new Promise<QueryResult>((resolve, reject) => {
            queued.push({ request, resolve, reject, queuedAt: performance.now(), context: options.context?.() ?? {} })
            if (streams < MAX_STREAMS && timer === null) {
                timer = setTimeout(flush, COALESCE_MS)
            }
        })
}

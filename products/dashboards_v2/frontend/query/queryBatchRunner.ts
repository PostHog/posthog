import { getCookie } from 'lib/api'

import { getDashboardV2QueryBatchCreateUrl } from 'products/dashboards/frontend/generated/api'
import type { QueryBatchRequestApi } from 'products/dashboards/frontend/generated/api.schemas'

import { type TimeRange } from '../filters/time/timeRangeSchema'
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
    signal?: AbortSignal
    retriedBusy?: boolean
}

// `unanswered` belongs to the stream, so a query answered busy and sent again counts as answered on its first stream.
type Running = { batch: Pending[]; controller: AbortController; unanswered: Map<number, Pending> }

export interface QueryBatchRunnerOptions {
    /** Read when a query is asked, and added to its batch's timing event, such as the tab on screen. */
    context?: () => Record<string, unknown>
    /**
     * Whether a query may read this project. Left out, a query may read only the runner's own project. A saved board
     * names its projects, so without this check a board could run queries as its viewer in a project the viewer never
     * chose, such as one in another organization.
     */
    allowsProject?: (project: number) => boolean
}

export const PROJECT_NOT_ALLOWED_ERROR = 'This chart queries a project outside your organization, so it was not run.'

// TODO(2026-11-25): Send no time when the request has none, once the query batch endpoint accepts that.
// The endpoint requires a time range on every query, so a query with no range of its own here gets this one.
const UNTIL_BATCH_ACCEPTS_NO_TIME: TimeRange = { from: 'now-7d', to: 'now' }

function batchTarget(request: QueryRequest, index: number): QueryBatchRequestApi['queries'][number] {
    const { query, legend } = request
    const time = request.time ?? UNTIL_BATCH_ACCEPTS_NO_TIME
    const refId = String(index)
    const target: QueryBatchRequestApi['queries'][number]['target'] =
        query.language === 'query'
            ? {
                  refId,
                  language: 'query',
                  // A `date_from` in its filters, even null, keeps the range saved in the query instead of `time`.
                  query: JSON.stringify(
                      request.time ? query.query : { query: query.query, filters: { date_from: null } }
                  ),
              }
            : { refId, language: query.language, query: query.query }
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

function hasLabels(labels: Record<string, string> | undefined): labels is Record<string, string> {
    return !!labels && Object.keys(labels).length > 0
}

export function toDataFrame(frame: Frame): DataFrame {
    return {
        ...(frame.name ? { name: frame.name } : {}),
        ...(hasLabels(frame.labels) ? { labels: frame.labels } : {}),
        ...(frame.meta ? { meta: frame.meta } : {}),
        ...(frame.hash ? { hash: frame.hash } : {}),
        fields: frame.fields.map((field) => ({
            name: field.name,
            type: field.type,
            values:
                field.type === 'time'
                    ? field.values.map((value) => timeLabel(value, field.unit === 'date'))
                    : field.values,
            ...(field.type !== 'time' && field.unit ? { unit: field.unit } : {}),
            ...(hasLabels(field.labels) ? { labels: field.labels } : {}),
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

function abortError(): Error {
    return new DOMException('Nothing waits for this query any more', 'AbortError')
}

async function postBatch(
    project: number,
    body: QueryBatchRequestApi,
    timer: QueryBatchTimer,
    signal: AbortSignal
): Promise<Response> {
    for (let attempt = 0; ; attempt++) {
        if (signal.aborted) {
            throw abortError()
        }
        timer.attempt()
        const response = await fetch(getDashboardV2QueryBatchCreateUrl(String(project)), {
            method: 'POST',
            credentials: 'same-origin',
            signal,
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
    project: number,
    { batch, controller, unanswered }: Running,
    timer: QueryBatchTimer,
    retry: (pending: Pending) => void
): Promise<void> {
    let error = new Error(NO_ANSWER)
    try {
        const response = await postBatch(
            project,
            {
                format: 'frames',
                queries: batch.map((pending, index) => batchTarget(pending.request, index)),
            },
            timer,
            controller.signal
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
                    const busy = line.error === BUSY_ERROR && !pending.retriedBusy && !pending.signal?.aborted
                    timer.line(line, busy)
                    if (busy) {
                        pending.retriedBusy = true
                        pending.queuedAt = performance.now()
                        retry(pending)
                    } else {
                        const result = resultFromLine(line)
                        if (result instanceof Error) {
                            pending.reject(result)
                        } else {
                            pending.resolve(result)
                        }
                    }
                    // `abandon` only checks when a query aborts, so a stream left holding only aborted queries
                    // after this answer stops here.
                    if (unanswered.size > 0 && [...unanswered.values()].every((one) => one.signal?.aborted)) {
                        controller.abort()
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
 * Up to `MAX_STREAMS` streams run at once, across every project, which stays inside the server's per-person shares
 * (`MAX_BATCHES_PER_USER` and `MAX_OPEN_BATCHES_PER_USER`). Charts that ask while every stream is open are sent
 * together once one ends. A query whose signal aborts leaves the queue, and a stream stops once every query still
 * waiting on it has aborted, so a closed dashboard or an old time range frees the slot.
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
    const running = new Set<Running>()
    const projectOf = (pending: Pending): number => pending.request.project ?? teamId

    const abandon = (pending: Pending): void => {
        pending.reject(abortError())
        const at = queued.indexOf(pending)
        if (at >= 0) {
            queued.splice(at, 1)
            return
        }
        for (const stream of running) {
            if (stream.batch.includes(pending) && [...stream.unanswered.values()].every((one) => one.signal?.aborted)) {
                stream.controller.abort()
            }
        }
    }

    const flush = (): void => {
        if (timer !== null) {
            clearTimeout(timer)
            timer = null
        }
        held = held.filter((entry) => {
            const ready = entry.due && entry.waitingOn.size === 0
            if (ready) {
                queued.push(...entry.busy.filter((pending) => !pending.signal?.aborted))
            }
            return !ready
        })
        while (streams < MAX_STREAMS && queued.length > 0) {
            // TODO(2026-11-26): Run each query in its own project on the server too, once subscriptions are reworked.
            // Only this client runner reads `project`, so a board rendered on the server would read one project.
            // The endpoint belongs to one project and checks this person's access to it, so a stream carries one
            // project's queries.
            const project = projectOf(queued[0])
            const batch = queued.filter((pending) => projectOf(pending) === project).slice(0, MAX_QUERIES_PER_BATCH)
            const sent = new Set(batch)
            queued = queued.filter((pending) => !sent.has(pending))
            streams++
            const id = nextStream++
            open.add(id)
            const busy: Pending[] = []
            const current: Running = {
                batch,
                controller: new AbortController(),
                unanswered: new Map(batch.map((pending, index) => [index, pending])),
            }
            running.add(current)
            const batchTimer = new QueryBatchTimer(board, batch)
            void runBatch(project, current, batchTimer, (pending) => busy.push(pending)).finally(() => {
                running.delete(current)
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

    return (request, signal) =>
        new Promise<QueryResult>((resolve, reject) => {
            if (signal?.aborted) {
                reject(abortError())
                return
            }
            const project = request.project ?? teamId
            if (project !== teamId && !options.allowsProject?.(project)) {
                reject(new Error(PROJECT_NOT_ALLOWED_ERROR))
                return
            }
            const pending: Pending = {
                request,
                resolve,
                reject,
                queuedAt: performance.now(),
                context: options.context?.() ?? {},
                signal,
            }
            signal?.addEventListener('abort', () => abandon(pending), { once: true })
            queued.push(pending)
            if (streams < MAX_STREAMS && timer === null) {
                timer = setTimeout(flush, COALESCE_MS)
            }
        })
}

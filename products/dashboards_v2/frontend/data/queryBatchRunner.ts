import { getCookie } from 'lib/api'

import { getDashboardV2QueryBatchCreateUrl } from 'products/dashboards/frontend/generated/api'
import type { QueryBatchRequestApi } from 'products/dashboards/frontend/generated/api.schemas'

import type { DataFrame, QueryRequest, QueryResult, RunQuery } from '../widgets/chart/vizTypes'
import { type Frame, type QueryBatchLine, readNdjson } from './queryBatchLines'

const NO_ANSWER = 'No answer came back for this query'
// The endpoint answers 429 while this person's earlier batches still hold its slots, which frees up within seconds.
const THROTTLE_RETRY_DELAYS_MS = [1000, 3000, 8000]
const MAX_QUERIES_PER_BATCH = 500

interface Pending {
    request: QueryRequest
    resolve: (result: QueryResult) => void
    reject: (error: Error) => void
}

function batchTarget(request: QueryRequest, index: number): QueryBatchRequestApi['queries'][number] {
    const { query, time } = request
    return {
        target:
            query.language === 'hogql'
                ? { refId: String(index), language: 'hogql', query: query.query }
                : { refId: String(index), language: 'query', query: JSON.stringify(query.query) },
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

async function postBatch(teamId: number, body: QueryBatchRequestApi): Promise<Response> {
    for (let attempt = 0; ; attempt++) {
        const response = await fetch(getDashboardV2QueryBatchCreateUrl(String(teamId)), {
            method: 'POST',
            credentials: 'same-origin',
            // No Accept header: DRF negotiates it against JSON renderers before the view streams, so
            // `application/x-ndjson` is refused with a 406.
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('posthog_csrftoken') || '',
            },
            body: JSON.stringify(body),
        })
        if (response.status !== 429 || attempt >= THROTTLE_RETRY_DELAYS_MS.length) {
            return response
        }
        await new Promise((resolve) => setTimeout(resolve, THROTTLE_RETRY_DELAYS_MS[attempt]))
    }
}

async function runBatch(teamId: number, batch: Pending[]): Promise<void> {
    const unanswered = new Map(batch.map((pending, index) => [index, pending]))
    let error = new Error(NO_ANSWER)
    try {
        const response = await postBatch(teamId, {
            format: 'frames',
            queries: batch.map((pending, index) => batchTarget(pending.request, index)),
        })
        if (!response.ok || !response.body) {
            error = new Error(`The query batch failed with status ${response.status}`)
        } else {
            await readNdjson(response.body, (line) => {
                const pending = unanswered.get(line.i)
                if (!pending) {
                    return
                }
                unanswered.delete(line.i)
                const result = resultFromLine(line)
                if (result instanceof Error) {
                    pending.reject(result)
                } else {
                    pending.resolve(result)
                }
            })
        }
    } catch (e) {
        error = e instanceof Error ? e : new Error(String(e))
    }
    // A rejected query leaves the chart cache, so the chart asks again the next time it mounts.
    unanswered.forEach((pending) => pending.reject(error))
}

/**
 * Runs chart queries through `POST dashboard_v2/query_batch/`. The charts that ask in the same tick, such as every
 * tile a dashboard mounts at once, share one stream, and each chart's promise settles as soon as its own line arrives.
 */
export function createQueryBatchRunner(teamId: number): RunQuery {
    let queued: Pending[] = []
    const flush = (): void => {
        const batch = queued
        queued = []
        for (let start = 0; start < batch.length; start += MAX_QUERIES_PER_BATCH) {
            void runBatch(teamId, batch.slice(start, start + MAX_QUERIES_PER_BATCH))
        }
    }
    return (request) =>
        new Promise<QueryResult>((resolve, reject) => {
            if (queued.length === 0) {
                setTimeout(flush, 0)
            }
            queued.push({ request, resolve, reject })
        })
}

import { z } from 'zod'

import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import type { Schema } from '@/core/schema'

import { ApiError, type PostHogApi } from './api'

// HogQLQueryResponse declares `columns` and `types` optional.
const HogQLResponse = z.looseObject({
    columns: z.array(z.string()).nullish(),
    types: z.array(z.tuple([z.string(), z.string()])).nullish(),
    results: z.array(z.array(z.unknown())),
    hasMore: z.boolean().nullish(),
})

export type HogQLResponse = z.output<typeof HogQLResponse>

// A query can join a run whose caller set its own `client_query_id`, which PostHog takes as free text
// of any length. The status route matches `[^/.]+`, so an ID with `/` or `.` can't be polled. The
// length cap only keeps junk out, and is not PostHog's.
const PostHogQueryId = z.string().regex(/^[^\s\p{Cc}\p{Cf}/.]{1,200}$/u, {
    error: 'The query ID has characters hog cannot send back to PostHog.',
})

const QueryStatus = z.looseObject({
    id: PostHogQueryId,
    complete: z.boolean().nullish(),
    error: z.boolean().nullish(),
    error_code: z.string().nullish(),
    error_message: z.string().nullish(),
    results: HogQLResponse.nullish(),
})

const StatusAnswer = z
    .object({ query_status: QueryStatus })
    .refine(({ query_status: status }) => !status.complete || status.error || status.results, {
        error: 'A finished query has no results.',
        path: ['query_status', 'results'],
    })

const RunningAnswer = z.looseObject({
    query_status: z.looseObject({ id: PostHogQueryId, complete: z.literal(false).nullish() }),
})

export type QueryState =
    | { state: 'done'; response: HogQLResponse }
    | { state: 'running'; id: string }
    | { state: 'failed'; error: HogError }

export type SettledState = Exclude<QueryState, { state: 'running' }>

// A cache hit is the whole HogQL response. Any other answer carries the status of the run PostHog
// started, next to stale results when the cache had some. A union would hide which field of the
// HogQL response is wrong, so the issues of that shape are the ones reported.
const StartAnswer = z.unknown().transform((raw, ctx): QueryState => {
    const running = RunningAnswer.safeParse(raw)
    if (running.success) {
        return { state: 'running', id: running.data.query_status.id }
    }

    const response = HogQLResponse.safeParse(raw)
    if (response.success) {
        return { state: 'done', response: response.data }
    }
    for (const issue of response.error.issues) {
        ctx.addIssue({ code: 'custom', message: issue.message, path: [...issue.path] })
    }
    return z.NEVER
})

const FIRST_POLL_MS = 500
const MAX_POLL_MS = 3_000
const POLL_BACKOFF = 1.5
const STATUS_TIMEOUT_MS = 15_000

function postHogQL<T>(
    api: PostHogApi,
    query: string,
    refresh: 'blocking' | 'force_blocking' | 'async',
    schema: Schema<T>,
    timeoutMs?: number
): Promise<T> {
    return api.post('query', { query: { kind: 'HogQLQuery', query }, refresh }, schema, { timeoutMs })
}

// Needs the `query:read` scope.
// `force_blocking` skips PostHog's cache, for a query whose answer has to be current.
export function runHogQL(
    api: PostHogApi,
    query: string,
    options: { timeoutMs?: number; refresh?: 'blocking' | 'force_blocking' } = {}
): Promise<HogQLResponse> {
    const { refresh = 'blocking', timeoutMs } = options
    return postHogQL(api, query, refresh, HogQLResponse, timeoutMs)
}

// `async` reads the cache as `blocking` does, but a query that has to run returns at once with its ID.
export function startHogQL(api: PostHogApi, query: string): Promise<QueryState> {
    return postHogQL(api, query, 'async', StartAnswer)
}

// A failure to reach PostHog throws instead of returning `failed`, because the query can still finish.
async function queryState(api: PostHogApi, id: string): Promise<QueryState> {
    let status: z.output<typeof QueryStatus>
    try {
        status = (await api.get(`query/${encodeURIComponent(id)}/`, StatusAnswer, { timeoutMs: STATUS_TIMEOUT_MS }))
            .query_status
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
            return {
                state: 'failed',
                error: new HogError(
                    'query_expired',
                    'PostHog no longer has the query or its results.',
                    'Run the query again with `hog query run <query>`.'
                ),
            }
        }

        // PostHog answers a failed query with its status: HTTP 400 when the query is at fault, 500 otherwise.
        const failed = error instanceof ApiError ? StatusAnswer.safeParse(error.body) : undefined
        if (!failed?.success) {
            throw error
        }
        status = failed.data.query_status
    }

    if (status.error) {
        return {
            state: 'failed',
            error: new HogError(
                status.error_code ?? 'query_failed',
                'The query failed in PostHog.',
                'Run `hog query check` on the query to see where it fails, or run it again.',
                undefined,
                undefined,
                status.error_message ?? undefined
            ),
        }
    }
    if (status.complete !== true || !status.results) {
        return { state: 'running', id }
    }
    return { state: 'done', response: status.results }
}

interface WaitOptions {
    deadline?: number
    pollFirst?: boolean
}

export function waitForQuery(
    runtime: Runtime,
    api: PostHogApi,
    id: string,
    options: WaitOptions & { deadline: number }
): Promise<QueryState>
export function waitForQuery(
    runtime: Runtime,
    api: PostHogApi,
    id: string,
    options: WaitOptions & { deadline?: undefined }
): Promise<SettledState>
export async function waitForQuery(
    runtime: Runtime,
    api: PostHogApi,
    id: string,
    { deadline, pollFirst = false }: WaitOptions
): Promise<QueryState> {
    let intervalMs = FIRST_POLL_MS
    let sleeps = !pollFirst
    for (;;) {
        if (sleeps) {
            const left = deadline === undefined ? intervalMs : deadline - runtime.now()
            if (left <= 0) {
                return { state: 'running', id }
            }
            await runtime.sleep(Math.min(intervalMs, left))
        }
        sleeps = true

        const state = await queryState(api, id)
        if (state.state !== 'running') {
            return state
        }
        intervalMs = Math.min(intervalMs * POLL_BACKOFF, MAX_POLL_MS)
    }
}

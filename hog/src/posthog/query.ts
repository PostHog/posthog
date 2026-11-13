import { z } from 'zod'

import { HogError } from '@/core/errors'
import type { Runtime } from '@/core/runtime'
import { parseOrThrow } from '@/core/schema'

import { ApiError, type PostHogApi } from './api'
import { QueryIdSchema, type QueryId } from './ids'

// HogQLQueryResponse declares `columns` and `types` optional.
const HogQLResponse = z.looseObject({
    columns: z.array(z.string()).nullish(),
    types: z.array(z.tuple([z.string(), z.string()])).nullish(),
    results: z.array(z.array(z.unknown())),
    hasMore: z.boolean().nullish(),
})

export type HogQLResponse = z.output<typeof HogQLResponse>

// Needs the `query:read` scope.
// `force_blocking` skips PostHog's cache, for a query whose answer has to be current.
export function runHogQL(
    api: PostHogApi,
    query: string,
    options: { timeoutMs?: number; refresh?: 'blocking' | 'force_blocking' } = {}
): Promise<HogQLResponse> {
    const { refresh = 'blocking', timeoutMs } = options
    return api.post('query', { query: { kind: 'HogQLQuery', query }, refresh }, HogQLResponse, { timeoutMs })
}

const QueryStatus = z.looseObject({
    id: QueryIdSchema,
    complete: z.boolean().nullish(),
    error: z.boolean().nullish(),
    error_code: z.string().nullish(),
    error_message: z.string().nullish(),
    results: z.unknown(),
})

// A cache hit is the whole HogQL response. Any other answer carries the status of the run PostHog started.
const StartAnswer = z.looseObject({ query_status: QueryStatus.nullish() })

const StatusAnswer = z.object({ query_status: QueryStatus })

export type QueryState =
    | { state: 'done'; response: HogQLResponse }
    | { state: 'running'; id: QueryId }
    | { state: 'failed'; error: HogError }

const FIRST_POLL_MS = 500
const MAX_POLL_MS = 3_000
const STATUS_TIMEOUT_MS = 15_000

function finished(response: unknown, path: string): QueryState {
    return {
        state: 'done',
        response: parseOrThrow(HogQLResponse, response, {
            code: 'unexpected_response',
            context: `PostHog's answer to ${path} isn't what hog expects.`,
            hint: 'Check that the host runs a recent version of PostHog.',
        }),
    }
}

// `async` reads the cache as `blocking` does, but a query that has to run returns at once with its ID.
export async function startHogQL(api: PostHogApi, query: string): Promise<QueryState> {
    const answer = await api.post('query', { query: { kind: 'HogQLQuery', query }, refresh: 'async' }, StartAnswer)
    if (answer.query_status && answer.query_status.complete !== true) {
        return { state: 'running', id: answer.query_status.id }
    }
    return finished(answer, 'POST query')
}

// A failure to reach PostHog throws instead of returning `failed`, because the query can still finish.
export async function queryState(api: PostHogApi, id: QueryId): Promise<QueryState> {
    let status: z.output<typeof QueryStatus>
    try {
        // PostHog answers a failed query with its status: HTTP 400 when the query is at fault, 500 otherwise.
        status = (
            await api.get(`query/${encodeURIComponent(id)}/`, StatusAnswer, {
                timeoutMs: STATUS_TIMEOUT_MS,
                answers: [400, 500],
            })
        ).query_status
    } catch (error) {
        if (error instanceof ApiError && error.status === 404) {
            return {
                state: 'failed',
                error: new HogError(
                    'query_expired',
                    `PostHog no longer has the query ${id} or its results.`,
                    'Run the query again with `hog query run <query>`.'
                ),
            }
        }
        throw error
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
    if (status.complete !== true) {
        return { state: 'running', id }
    }
    return finished(status.results, 'GET query status')
}

export async function waitForQuery(
    runtime: Runtime,
    api: PostHogApi,
    id: QueryId,
    deadline: number | undefined
): Promise<QueryState> {
    let intervalMs = FIRST_POLL_MS
    for (;;) {
        const left = deadline === undefined ? intervalMs : deadline - runtime.now()
        if (left <= 0) {
            return { state: 'running', id }
        }
        await runtime.sleep(Math.min(intervalMs, left))

        const state = await queryState(api, id)
        if (state.state !== 'running') {
            return state
        }
        intervalMs = Math.min(intervalMs * 1.5, MAX_POLL_MS)
    }
}

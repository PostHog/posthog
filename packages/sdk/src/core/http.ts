// Isomorphic fetch-based HTTP transport. Ported from the `fetch`/`request`/
// `fetchJson` methods of services/mcp/src/api/client.ts, dropping MCP-only
// concerns (session/conversation headers, SSE, mcpConsumer). No node-only
// imports; `fetch` is injectable.

import { type FetchLike, normalizeHost, type RequestOptions } from './config'
import {
    parseRetryAfterSeconds,
    PostHogApiError,
    PostHogPermissionError,
    PostHogRateLimitError,
    PostHogValidationError,
} from './errors'

// Outbound 429 retry policy. The API is the source of truth for rate limits, so
// we honor its Retry-After signal and fall back to jittered exponential backoff
// when the header is missing. The total wait budget bounds how long a throttled
// call can stay open across all retries combined.
const RATE_LIMIT_MAX_RETRIES = 3
const RATE_LIMIT_BASE_BACKOFF_MS = 2000
const RATE_LIMIT_TOTAL_WAIT_BUDGET_MS = 30_000

const HTTP_METHODS = ['GET', 'POST', 'PATCH', 'PUT', 'DELETE'] as const
export type HttpMethod = (typeof HTTP_METHODS)[number]

export interface HttpClientOptions {
    apiKey: string
    host: string
    fetch?: FetchLike | undefined
    headers?: Record<string, string> | undefined
    userAgent?: string | undefined
}

export interface HttpRequest {
    method: HttpMethod
    path: string
    body?: Record<string, unknown> | unknown[] | undefined
    query?: Record<string, unknown> | undefined
    /** Per-call overrides (abort signal, extra headers). */
    opts?: RequestOptions | undefined
}

/**
 * Builds a query string from a record, matching the MCP client's serialization:
 * skips null/undefined and empty arrays, and JSON-stringifies objects/arrays so
 * backends that `json.loads()` query params work correctly.
 */
export function serializeQuery(query: Record<string, unknown> | undefined): string {
    if (!query) {
        return ''
    }
    const searchParams = new URLSearchParams()
    for (const [k, v] of Object.entries(query)) {
        if (v === undefined || v === null) {
            continue
        }
        if (Array.isArray(v) && v.length === 0) {
            continue
        }
        if (typeof v === 'object') {
            searchParams.append(k, JSON.stringify(v))
        } else {
            searchParams.append(k, String(v))
        }
    }
    return searchParams.toString()
}

export class HttpClient {
    private readonly apiKey: string
    private readonly baseUrl: string
    private readonly fetchImpl: FetchLike
    private readonly defaultHeaders: Record<string, string>

    constructor(options: HttpClientOptions) {
        this.apiKey = options.apiKey
        this.baseUrl = normalizeHost(options.host)
        const injected = options.fetch
        const globalFetch = (globalThis as { fetch?: FetchLike }).fetch
        const resolved = injected ?? (globalFetch ? globalFetch.bind(globalThis) : undefined)
        if (!resolved) {
            throw new Error(
                'No `fetch` implementation available. Pass `fetch` to createClient() on a runtime without a global fetch.'
            )
        }
        this.fetchImpl = resolved
        this.defaultHeaders = {
            Authorization: `Bearer ${this.apiKey}`,
            ...(options.userAgent ? { 'User-Agent': options.userAgent } : {}),
            'X-PostHog-Client': 'sdk',
            ...(options.headers ?? {}),
        }
    }

    /** Generic HTTP request with auth, retry, and typed error mapping. */
    async request<T = unknown>(req: HttpRequest): Promise<T> {
        const qs = serializeQuery(req.query)
        const url = `${this.baseUrl}${req.path}${qs ? `?${qs}` : ''}`
        const headers: Record<string, string> = { ...this.defaultHeaders, ...(req.opts?.headers ?? {}) }
        if (req.body !== undefined) {
            headers['Content-Type'] = 'application/json'
        }
        const init: RequestInit = {
            method: req.method,
            headers,
            ...(req.body !== undefined ? { body: JSON.stringify(req.body) } : {}),
            ...(req.opts?.signal ? { signal: req.opts.signal } : {}),
        }
        return this.fetchWithRetry<T>(url, init, req.method)
    }

    private async fetchWithRetry<T>(url: string, init: RequestInit, method: HttpMethod): Promise<T> {
        let waitBudgetMs = RATE_LIMIT_TOTAL_WAIT_BUDGET_MS

        for (let attempt = 0; attempt <= RATE_LIMIT_MAX_RETRIES; attempt++) {
            const response = await this.fetchImpl(url, init)

            if (response.status === 429) {
                const retryAfterSeconds = parseRetryAfterSeconds(response.headers.get('Retry-After'))
                if (attempt === RATE_LIMIT_MAX_RETRIES) {
                    throw new PostHogRateLimitError({ body: await response.text(), url, method, retryAfterSeconds })
                }
                // DRF rejects throttled requests before the view runs, so retrying
                // is safe for mutations too.
                const backoffMs = RATE_LIMIT_BASE_BACKOFF_MS * 2 ** attempt
                const delayMs =
                    retryAfterSeconds !== null
                        ? retryAfterSeconds * 1000
                        : // Equal jitter so concurrent 429s don't retry in lockstep.
                          backoffMs / 2 + Math.random() * (backoffMs / 2)
                if (delayMs > waitBudgetMs) {
                    throw new PostHogRateLimitError({ body: await response.text(), url, method, retryAfterSeconds })
                }
                waitBudgetMs -= delayMs
                await sleep(delayMs)
                continue
            }

            if (!response.ok) {
                throw await mapErrorResponse(response, url, method)
            }

            const rawText = await response.text()
            if (!rawText) {
                return {} as T
            }
            try {
                return JSON.parse(rawText) as T
            } catch {
                return rawText as unknown as T
            }
        }

        // Unreachable: the final attempt always returns or throws above.
        throw new Error('Unexpected rate limit retry state')
    }
}

async function mapErrorResponse(response: Response, url: string, method: string): Promise<Error> {
    const errorText = await response.text()
    let errorData: { code?: string; detail?: string; type?: string; attr?: string; extra?: unknown }
    try {
        errorData = JSON.parse(errorText)
    } catch {
        errorData = { detail: errorText }
    }

    if (response.status === 403 && errorData?.code === 'permission_denied') {
        const scopeMatch = /required scope ['"]([^'"]+)['"]/.exec(errorData.detail || '')
        return new PostHogPermissionError({
            detail: errorData.detail || 'permission denied',
            missingScope: scopeMatch?.[1],
            url,
            method,
        })
    }

    if (errorData.type === 'validation_error') {
        return new PostHogValidationError({
            detail: errorData.detail || errorData.code || 'unknown',
            attr: errorData.attr ?? undefined,
            code: errorData.code ?? undefined,
            extra: (errorData.extra ?? undefined) as Record<string, unknown> | undefined,
            url,
            method,
        })
    }

    return new PostHogApiError({
        status: response.status,
        statusText: response.statusText,
        body: errorText,
        url,
        method,
    })
}

function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
}

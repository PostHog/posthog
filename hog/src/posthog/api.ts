import { HogError } from '@/core/errors'
import { parseLossless } from '@/core/raw-json'
import type { RuntimeFetch } from '@/core/runtime'
import { VERSION } from '@/version'

import type { Credentials } from './credentials'

export const USER_AGENT = `hog/${VERSION}`
// Generous, because a HogQL query can run for minutes. It only stops a connection that hangs.
const REQUEST_TIMEOUT_MS = 10 * 60 * 1000

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

export interface HttpRequest {
    method: Method
    body?: unknown
    apiKey?: string
    timeoutMs?: number
}

export interface HttpResponse {
    status: number
    ok: boolean
    json: unknown
    text: string
}

// Sends one JSON request to PostHog. Any failure before the whole body arrives, including the
// deadline, is a `network_error`, so callers handle a dropped connection in one place.
export async function sendRequest(fetchFn: RuntimeFetch, url: URL, request: HttpRequest): Promise<HttpResponse> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json', 'User-Agent': USER_AGENT }
    if (request.apiKey) {
        headers.Authorization = `Bearer ${request.apiKey}`
    }
    let response: Response
    let text: string
    try {
        response = await fetchFn(url, {
            method: request.method,
            headers,
            body: request.body === undefined ? undefined : JSON.stringify(request.body),
            timeoutMs: request.timeoutMs ?? REQUEST_TIMEOUT_MS,
        })
        text = await response.text()
    } catch (error) {
        throw new HogError(
            'network_error',
            `hog couldn't reach ${url.origin}: ${error instanceof Error ? error.message : String(error)}`,
            'Check the host and your network connection.'
        )
    }
    let json: unknown
    try {
        json = text ? parseLossless(text) : undefined
    } catch {
        json = undefined
    }
    return { status: response.status, ok: response.ok, json, text }
}

// A non-2xx answer from PostHog. `type` is the DRF error type, such as `validation_error`.
export class ApiError extends HogError {
    constructor(
        readonly status: number,
        readonly type: string | undefined,
        code: string,
        message: string,
        hint?: string
    ) {
        super(code, message, hint)
    }

    override withHint(hint: string): ApiError {
        return new ApiError(this.status, this.type, this.code, this.message, hint)
    }
}

export class PostHogApi {
    constructor(
        private readonly credentials: Credentials,
        private readonly fetchFn: RuntimeFetch
    ) {}

    // Paths are relative to the project, so `query` is /api/environments/<project id>/query. A path
    // that starts with `/`, like `/api/users/@me/`, is relative to the host instead.
    private url(path: string): URL {
        const base = path.startsWith('/')
            ? this.credentials.host
            : new URL(`api/environments/${this.credentials.projectId}/`, this.credentials.host)
        return new URL(path, base)
    }

    get<T>(path: string): Promise<T> {
        return this.request<T>('GET', path)
    }

    post<T>(path: string, body: unknown): Promise<T> {
        return this.request<T>('POST', path, body)
    }

    patch<T>(path: string, body: unknown): Promise<T> {
        return this.request<T>('PATCH', path, body)
    }

    delete<T>(path: string): Promise<T> {
        return this.request<T>('DELETE', path)
    }

    private async request<T>(method: Method, path: string, body?: unknown): Promise<T> {
        const response = await sendRequest(this.fetchFn, this.url(path), {
            method,
            body,
            apiKey: this.credentials.apiKey,
        })
        if (response.text && response.json === undefined) {
            throw new HogError(
                'unexpected_response',
                `PostHog answered with HTTP ${response.status} and a body that isn't JSON.`,
                response.status === 404 ? 'Check the host and the project ID.' : undefined
            )
        }
        if (!response.ok) {
            throw this.failure(response.status, response.json)
        }
        return response.json as T
    }

    private failure(status: number, body: unknown): ApiError {
        const error = (body ?? {}) as { type?: string; code?: string; detail?: string }
        const hints: Record<number, string> = {
            401: 'Check that the personal API key is valid.',
            403: 'Check that the personal API key has access to this project.',
            404: 'Check the host and the project ID.',
        }
        return new ApiError(
            status,
            error.type,
            error.code ?? `http_${status}`,
            error.detail ?? `PostHog answered with HTTP ${status}.`,
            hints[status]
        )
    }
}

import { z } from 'zod'

import { HogError } from '@/core/errors'
import { parseJsonOrUndefined } from '@/core/json'
import type { RuntimeFetch } from '@/core/runtime'
import { VERSION } from '@/version'

import { hostUrl } from './host'
import type { KeySession } from './key-session'

export const USER_AGENT = `hog/${VERSION}`
// Generous, because a HogQL query can run for minutes. It only stops a connection that hangs.
const REQUEST_TIMEOUT_MS = 10 * 60 * 1000

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

export interface HttpRequest {
    method: Method
    body?: unknown
    // Sent form encoded instead of `body`, as the OAuth endpoints expect.
    form?: Record<string, string>
    token?: string
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
    const headers: Record<string, string> = {
        'Content-Type': request.form ? 'application/x-www-form-urlencoded' : 'application/json',
        'User-Agent': USER_AGENT,
    }
    if (request.token) {
        headers.Authorization = `Bearer ${request.token}`
    }
    let response: Response
    let text: string
    try {
        response = await fetchFn(url, {
            method: request.method,
            headers,
            body: request.form
                ? new URLSearchParams(request.form).toString()
                : request.body === undefined
                  ? undefined
                  : JSON.stringify(request.body),
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
    // Callers check `json` against a schema of their own. A body that isn't JSON leaves it undefined.
    const json = text ? parseJsonOrUndefined(text, z.unknown(), { lossless: true }) : undefined
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
        private readonly session: KeySession,
        private readonly fetchFn: RuntimeFetch
    ) {}

    // Paths are relative to the project, so `query` is /api/environments/<project id>/query. A path
    // that starts with `/`, like `/api/users/@me/`, is relative to the host instead.
    private url(path: string): URL {
        const { host, projectId } = this.session.current
        // hostUrl keeps the path a self-hosted PostHog can sit under, which `new URL` would drop. A
        // path from a pagination link already starts with it.
        const root = hostUrl(host, '')
        let url: URL
        if (path.startsWith('/')) {
            url = path.startsWith(root.pathname) ? new URL(path, root) : hostUrl(host, path.slice(1))
        } else {
            url = new URL(path, hostUrl(host, `api/environments/${projectId}/`))
        }
        // A path from a link PostHog sent, such as `//other.example/`, must not carry the token elsewhere.
        if (url.origin !== root.origin) {
            throw new HogError('unexpected_response', `PostHog sent a link to another host: ${url.origin}.`)
        }
        return url
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
        const url = this.url(path)
        const response = await this.session.send(
            (token) => sendRequest(this.fetchFn, url, { method, body, token }),
            (answer) => answer.status === 401
        )
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

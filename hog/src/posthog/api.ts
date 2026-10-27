import { HogError } from '@/core/errors'
import { VERSION } from '@/version'

import type { Credentials } from './credentials'

const USER_AGENT = `hog/${VERSION}`

type Method = 'GET' | 'POST' | 'PATCH' | 'DELETE'

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
}

export class PostHogApi {
    constructor(
        private readonly credentials: Credentials,
        private readonly fetchFn: typeof fetch
    ) {}

    // Paths are relative to the project, so `query` is /api/environments/<project id>/query.
    private environmentUrl(path: string): URL {
        return new URL(path, new URL(`api/environments/${this.credentials.projectId}/`, this.credentials.host))
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
        let response: Response
        try {
            response = await this.fetchFn(this.environmentUrl(path), {
                method,
                headers: {
                    Authorization: `Bearer ${this.credentials.apiKey}`,
                    'Content-Type': 'application/json',
                    'User-Agent': USER_AGENT,
                },
                body: body === undefined ? undefined : JSON.stringify(body),
            })
        } catch (error) {
            throw new HogError(
                'network_error',
                `hog couldn't reach ${this.credentials.host}: ${error instanceof Error ? error.message : String(error)}`,
                'Check the host and your network connection.'
            )
        }

        const text = await response.text()
        let parsed: unknown
        try {
            parsed = text ? JSON.parse(text) : undefined
        } catch {
            throw new HogError(
                'unexpected_response',
                `PostHog answered with HTTP ${response.status} and a body that isn't JSON.`,
                response.status === 404 ? 'Check the host and the project ID.' : undefined
            )
        }
        if (!response.ok) {
            throw this.failure(response.status, parsed)
        }
        return parsed as T
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

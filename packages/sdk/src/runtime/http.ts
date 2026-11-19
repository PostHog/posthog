import { PostHogError } from '../errors.js'
import type { ApiFieldError, JsonValue, RequestOptions, ResponseMeta } from '../types.js'
import { type ResolvedConfig, validateTimeout } from './config.js'

export interface HttpResult {
    data: JsonValue
    meta: ResponseMeta
}

export function isObject(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function waitWithSignal<T>(work: Promise<T>, signal: AbortSignal): Promise<T> {
    return new Promise((resolve, reject) => {
        const abort = (): void => reject(signal.reason)
        signal.addEventListener('abort', abort, { once: true })
        work.then(resolve, reject).finally(() => signal.removeEventListener('abort', abort))
        if (signal.aborted) {
            abort()
        }
    })
}

export async function withDeadline<T>(
    options: RequestOptions,
    defaultTimeout: number,
    run: (signal: AbortSignal) => Promise<T>
): Promise<T> {
    const timeoutMs = validateTimeout(options.timeoutMs ?? defaultTimeout)
    const controller = new AbortController()
    const abort = (): void =>
        controller.abort(new PostHogError({ kind: 'aborted', message: 'The PostHog request was canceled.' }))
    const timer = setTimeout(
        () =>
            controller.abort(
                new PostHogError({ kind: 'timeout', message: 'The PostHog request exceeded its deadline.' })
            ),
        timeoutMs
    )
    options.signal?.addEventListener('abort', abort, { once: true })
    if (options.signal?.aborted) {
        abort()
    }
    try {
        if (controller.signal.aborted) {
            throw controller.signal.reason
        }
        return await waitWithSignal(run(controller.signal), controller.signal)
    } finally {
        clearTimeout(timer)
        options.signal?.removeEventListener('abort', abort)
    }
}

function retryAfter(value: string | null): number | undefined {
    if (!value) {
        return undefined
    }
    const seconds = Number(value)
    const result = Number.isFinite(seconds) ? seconds * 1000 : Date.parse(value) - Date.now()
    return Number.isFinite(result) ? Math.max(0, result) : undefined
}

function apiFields(data: JsonValue): ApiFieldError[] {
    if (!isObject(data)) {
        return []
    }
    const errors = Array.isArray(data.errors) ? data.errors : [data]
    return errors.flatMap((error) => {
        if (!isObject(error) || typeof error.attr !== 'string' || typeof error.detail !== 'string') {
            return []
        }
        return [
            {
                path: error.attr.split('.'),
                code: typeof error.code === 'string' ? error.code : 'invalid',
                message: error.detail,
            },
        ]
    })
}

export async function request(
    config: ResolvedConfig,
    path: string,
    init: RequestInit,
    signal: AbortSignal
): Promise<HttpResult> {
    if (signal.aborted) {
        throw signal.reason
    }
    const headers = new Headers(init.headers)
    headers.set('Accept', 'application/json')
    if (config.authMode === 'token') {
        headers.set('Authorization', `Bearer ${config.token}`)
    } else {
        headers.delete('Authorization')
    }
    let response: Response
    try {
        response = await config.fetch(`${config.baseUrl}/${path.replace(/^\/+/, '')}`, {
            ...init,
            headers,
            signal,
            redirect: 'error',
        })
    } catch (cause) {
        if (signal.aborted) {
            throw signal.reason
        }
        throw new PostHogError(
            { kind: 'transport', message: 'The PostHog request could not reach the API.' },
            { cause }
        )
    }
    const requestId = response.headers.get('x-request-id') ?? undefined
    const meta: ResponseMeta = { status: response.status, ...(requestId ? { requestId } : {}) }
    let data: JsonValue = null
    try {
        const text = await response.text()
        if (text) {
            try {
                data = JSON.parse(text) as JsonValue
            } catch {
                if (response.ok) {
                    throw new PostHogError({
                        kind: 'response_validation',
                        message: 'The PostHog API returned invalid JSON.',
                        ...meta,
                    })
                }
            }
        }
    } catch (cause) {
        if (signal.aborted) {
            throw signal.reason
        }
        if (cause instanceof PostHogError) {
            throw cause
        }
        throw new PostHogError(
            { kind: 'transport', message: 'The PostHog response could not be read.', ...meta },
            { cause }
        )
    }
    if (!response.ok) {
        const message =
            isObject(data) && typeof data.detail === 'string'
                ? data.detail
                : `PostHog returned HTTP ${response.status}.`
        const code = isObject(data) && typeof data.code === 'string' ? data.code : undefined
        const retryAfterMs = retryAfter(response.headers.get('retry-after'))
        const fields = apiFields(data)
        throw new PostHogError({
            kind: 'api',
            message,
            ...meta,
            ...(code ? { code } : {}),
            ...(retryAfterMs !== undefined ? { retryAfterMs } : {}),
            ...(fields.length ? { fields } : {}),
            body: data,
        })
    }
    return { data, meta }
}

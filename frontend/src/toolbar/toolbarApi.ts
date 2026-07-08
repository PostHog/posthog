import { encodeParams } from 'kea-router'

import type { PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarFetch } from '~/toolbar/toolbarFetch'
import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException } from '~/toolbar/toolbarPosthogJS'
import type { ElementsEventType, WebExperiment } from '~/toolbar/types'
import type { ActionType, CombinedFeatureFlagAndValueType, EventDefinition, ProductTour, Survey } from '~/types'

/**
 * The single, blessed way to talk to the PostHog API from the toolbar.
 *
 * Every authenticated data request should go through `toolbarApi` — preferably one of its
 * resource namespaces (`toolbarApi.actions.list()`, `toolbarApi.surveys.update(id, …)`), which
 * own the route strings (see the `toolbarApi` export below for the full contract). It wraps
 * `toolbarFetch` (which owns the OAuth bearer + token refresh) and folds the eight different
 * ad-hoc failure-handling styles the toolbar had grown into one consistent contract:
 *
 *   - It never throws. Network-level failures (CORS, offline, a customer page that
 *     replaced `window.fetch`) are caught and returned as a normal failure result,
 *     so no caller needs a `try/catch` and no listener can leak an unhandled rejection.
 *   - It always parses the body and returns a discriminated-union `ToolbarApiResult`,
 *     so every call site branches on `result.ok` the same way.
 *   - It centralizes observability: every failure is logged via `toolbarLogger`, and
 *     genuinely-unexpected failures (5xx, malformed JSON) are reported to error tracking.
 *     Auth (401/403), other client (4xx), and network-level errors are expected outcomes —
 *     they are logged but not reported as exceptions.
 *   - Per-request telemetry (`toolbar api request`) is emitted by `toolbarFetch` itself.
 *
 * What stays at the call site is only what is genuinely call-site specific: the
 * fallback value to use on failure, and any feature side effects (e.g. resetting a
 * form, disabling a mode). Toasting and re-authentication are opt-in via options so
 * that loaders stay quiet while user-initiated writes can surface a message.
 *
 * Auth flows (OAuth code exchange, token refresh, the reachability HEAD check) and the
 * pre-mount feature-flag preload deliberately do NOT use this — they run before the
 * toolbar is authenticated (or before kea is mounted) and own their own fetch behavior.
 */

export type ToolbarApiMethod = 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'

export interface ToolbarApiErrorInfo {
    /** HTTP status, or 0 for a network-level failure that never reached the server. */
    status: number
    /** Best human-readable message extracted from the response body, or a fallback. */
    detail: string
    /** Parsed JSON body, when there was one. */
    body: unknown
    /** 401/403 — the session is missing, expired, or lacks access. Handled by the auth flow. */
    isAuthError: boolean
    /** The request never completed (CORS, offline, aborted, customer fetch wrapper threw). */
    isNetworkError: boolean
}

export type ToolbarApiResult<T> =
    | { ok: true; status: number; data: T }
    | { ok: false; status: number; data: null; error: ToolbarApiErrorInfo }

export interface ToolbarApiOptions {
    /**
     * Identifies the call site in logs, telemetry, and error tracking, e.g. `'load_actions'`.
     * Use a short snake_case string.
     */
    context: string
    /**
     * Surface a `lemonToast.error` when the request fails. Pass `true` to show the
     * extracted error detail, or a string to use as the fallback message when the
     * response carries no specific detail. Defaults to `false` (silent — the failure
     * is still logged and, when unexpected, reported). Prefer `false` for background
     * loaders and a string for user-initiated writes.
     */
    toastOnError?: boolean | string
    /**
     * Re-trigger the OAuth flow when the request returns 403 (project access lost or the
     * user switched projects). `toolbarFetch` already clears the session on 403; this
     * additionally kicks off re-authentication. Defaults to `false`.
     */
    reauthenticateOnForbidden?: boolean
    /**
     * Report unexpected failures (5xx / malformed JSON) to error tracking. Defaults to
     * `true`. Network-level failures are never reported regardless of this flag — they are
     * expected outcomes (ad blockers, CORS, offline, customer fetch wrappers). Set to
     * `false` when the caller deliberately re-raises the failure (e.g. a kea loader that
     * throws to drive its own `*Failure` reducer) so the exception is only captured once.
     */
    captureOnError?: boolean
    /**
     * Passed through to `toolbarFetch`. Use `'use-as-provided'` for pagination URLs that
     * come from a response body (they are pinned to the uiHost/apiHost origin). Defaults
     * to `'full'`.
     */
    urlConstruction?: 'full' | 'use-as-provided'
}

/** Pull a human-readable message out of a (possibly DRF) error body. */
export function extractErrorDetail(body: unknown, status: number, fallback: string): string {
    if (status === 401 || status === 403) {
        return 'Your toolbar session lacks permission. Please re-authenticate the toolbar from PostHog.'
    }
    if (body && typeof body === 'object') {
        const obj = body as Record<string, unknown>
        if (typeof obj.detail === 'string' && obj.detail) {
            return obj.detail
        }
        // Surface DRF field-level errors: { name: ["..."], questions: [...] }.
        const fieldMessages: string[] = []
        for (const [key, value] of Object.entries(obj)) {
            if (Array.isArray(value) && value.length > 0 && typeof value[0] === 'string') {
                fieldMessages.push(`${key}: ${value[0]}`)
            } else if (typeof value === 'string') {
                fieldMessages.push(`${key}: ${value}`)
            }
        }
        if (fieldMessages.length > 0) {
            return fieldMessages.join('; ')
        }
    }
    return fallback
}

function pathnameForLog(url: string): string {
    try {
        // url may be a path ("/api/…") or an absolute pagination URL — both parse against a base.
        return new URL(url, 'http://x').pathname
    } catch {
        return url
    }
}

function emitToast(toastOnError: boolean | string, error: ToolbarApiErrorInfo): void {
    if (!toastOnError) {
        return
    }
    const fallback = typeof toastOnError === 'string' ? toastOnError : error.detail
    lemonToast.error(extractErrorDetail(error.body, error.status, fallback))
}

async function request<T>(
    method: ToolbarApiMethod,
    url: string,
    payload: Record<string, any> | FormData | undefined,
    options: ToolbarApiOptions
): Promise<ToolbarApiResult<T>> {
    const {
        context,
        toastOnError = false,
        reauthenticateOnForbidden = false,
        captureOnError = true,
        urlConstruction = 'full',
    } = options
    const pathname = pathnameForLog(url)

    let response: Response
    try {
        response = await toolbarFetch(url, method, payload, urlConstruction)
    } catch {
        const error: ToolbarApiErrorInfo = {
            status: 0,
            detail: 'Network error',
            body: null,
            isAuthError: false,
            isNetworkError: true,
        }
        // Network-level failures (ad blockers, CORS, offline, a customer page that wraps or
        // replaces `window.fetch`) are expected outcomes the toolbar already soft-fails on.
        // Log them like 4xx errors, but don't escalate to error tracking where they'd bury
        // genuine toolbar failures as recurring "Failed to fetch" noise.
        toolbarLogger.warn('api', `Request failed (network): ${context}`, { context, method, pathname })
        emitToast(toastOnError, error)
        return { ok: false, status: 0, data: null, error }
    }

    const status = response.status

    if (response.ok) {
        // DELETE responses are typically 204/empty — don't try to parse a body we won't use.
        if (method === 'DELETE') {
            return { ok: true, status, data: null as T }
        }
        try {
            const data = (await response.json()) as T
            return { ok: true, status, data }
        } catch (e) {
            const error: ToolbarApiErrorInfo = {
                status,
                detail: 'The server returned a malformed response.',
                body: null,
                isAuthError: false,
                isNetworkError: false,
            }
            toolbarLogger.error('api', `Response was not valid JSON: ${context}`, { context, method, pathname, status })
            if (captureOnError) {
                captureToolbarException(e, context, { reason: 'invalid_json', status })
            }
            emitToast(toastOnError, error)
            return { ok: false, status, data: null, error }
        }
    }

    const body = await response.json().catch(() => null)
    const isAuthError = status === 401 || status === 403
    const isServerError = status >= 500
    const error: ToolbarApiErrorInfo = {
        status,
        detail: extractErrorDetail(body, status, 'Request failed'),
        body,
        isAuthError,
        isNetworkError: false,
    }

    if (status === 403 && reauthenticateOnForbidden) {
        toolbarConfigLogic.actions.authenticate()
    }

    // Server errors are unexpected and worth an exception; auth and other client errors
    // are expected outcomes (stale session, validation) — log them but don't report.
    if (isServerError) {
        toolbarLogger.error('api', `Request failed (server): ${context}`, { context, method, pathname, status })
        if (captureOnError) {
            captureToolbarException(new Error(`${context}: HTTP ${status}`), context, { status })
        }
    } else {
        toolbarLogger.warn('api', `Request failed: ${context}`, { context, method, pathname, status })
    }

    emitToast(toastOnError, error)
    return { ok: false, status, data: null, error }
}

function apiGet<T = unknown>(url: string, options: ToolbarApiOptions): Promise<ToolbarApiResult<T>> {
    return request<T>('GET', url, undefined, options)
}
function apiPost<T = unknown>(
    url: string,
    payload: Record<string, any> | FormData | undefined,
    options: ToolbarApiOptions
): Promise<ToolbarApiResult<T>> {
    return request<T>('POST', url, payload, options)
}
function apiPatch<T = unknown>(
    url: string,
    payload: Record<string, any> | FormData | undefined,
    options: ToolbarApiOptions
): Promise<ToolbarApiResult<T>> {
    return request<T>('PATCH', url, payload, options)
}
function apiDelete<T = unknown>(url: string, options: ToolbarApiOptions): Promise<ToolbarApiResult<T>> {
    return request<T>('DELETE', url, undefined, options)
}

const PROJECT = '/api/projects/@current'
const ENVIRONMENT = '/api/environments/@current'

/**
 * `toolbarApi` is the single entry point for talking to the PostHog API from the toolbar.
 *
 * Prefer the resource namespaces (`toolbarApi.actions.list()`, `toolbarApi.surveys.update(id, …)`):
 * they own the route strings so every `/api/projects/@current/…` path lives in exactly one place
 * and call sites read as intent rather than URLs. Each method takes the resource-specific arguments
 * (id, payload, query) plus a `ToolbarApiOptions` and returns the same `ToolbarApiResult<T>`, so
 * failure handling stays identical everywhere.
 *
 * The bare verb methods (`get`/`post`/`patch`/`delete`) remain as the low-level primitive that the
 * namespaces are built on — reach for them only for a one-off route not yet modeled as a resource.
 */
export const toolbarApi = {
    get: apiGet,
    post: apiPost,
    patch: apiPatch,
    delete: apiDelete,

    actions: {
        list: (options: ToolbarApiOptions): Promise<ToolbarApiResult<{ results: ActionType[] }>> =>
            apiGet(`${PROJECT}/actions/`, options),
        create: (payload: Record<string, any>, options: ToolbarApiOptions): Promise<ToolbarApiResult<ActionType>> =>
            apiPost(`${PROJECT}/actions/`, payload, options),
        update: (
            id: number | string,
            payload: Record<string, any>,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<ActionType>> => apiPatch(`${PROJECT}/actions/${id}/`, payload, options),
    },

    webExperiments: {
        list: (options: ToolbarApiOptions): Promise<ToolbarApiResult<{ results: WebExperiment[] }>> =>
            apiGet(`${PROJECT}/web_experiments/`, options),
        create: (payload: Record<string, any>, options: ToolbarApiOptions): Promise<ToolbarApiResult<WebExperiment>> =>
            apiPost(`${PROJECT}/web_experiments/`, payload, options),
        update: (
            id: number | string,
            payload: Record<string, any>,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<WebExperiment>> => apiPatch(`${PROJECT}/web_experiments/${id}/`, payload, options),
    },

    productTours: {
        list: (options: ToolbarApiOptions): Promise<ToolbarApiResult<{ results?: ProductTour[] } | ProductTour[]>> =>
            apiGet(`${PROJECT}/product_tours/`, options),
        create: (payload: Record<string, any>, options: ToolbarApiOptions): Promise<ToolbarApiResult<ProductTour>> =>
            apiPost(`${PROJECT}/product_tours/`, payload, options),
        updateDraft: (
            id: number | string,
            payload: Record<string, any>,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<ProductTour>> =>
            apiPatch(`${PROJECT}/product_tours/${id}/draft/`, payload, options),
        delete: (id: number | string, options: ToolbarApiOptions): Promise<ToolbarApiResult<null>> =>
            apiDelete(`${PROJECT}/product_tours/${id}/`, options),
    },

    fieldNotes: {
        listPending: <T = unknown>(options: ToolbarApiOptions): Promise<ToolbarApiResult<T>> =>
            apiGet<T>(`${PROJECT}/field_notes/?field_note_status=pending`, options),
        create: <T = unknown>(payload: Record<string, any>, options: ToolbarApiOptions): Promise<ToolbarApiResult<T>> =>
            apiPost<T>(`${PROJECT}/field_notes/`, payload, options),
        delete: (id: number | string, options: ToolbarApiOptions): Promise<ToolbarApiResult<null>> =>
            apiDelete(`${PROJECT}/field_notes/${id}/`, options),
    },

    surveys: {
        list: (
            params: { limit: number; offset: number; search?: string },
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<{ results?: Survey[]; next?: string | null }>> =>
            apiGet(`${PROJECT}/surveys/${encodeParams({ archived: false, ...params }, '?')}`, options),
        create: (
            payload: Record<string, any>,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<{ id?: string }>> => apiPost(`${PROJECT}/surveys/`, payload, options),
        update: (
            id: number | string,
            payload: Record<string, any>,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<{ id?: string }>> => apiPatch(`${PROJECT}/surveys/${id}/`, payload, options),
    },

    featureFlags: {
        myFlags: (
            params: Record<string, any>,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<CombinedFeatureFlagAndValueType[]>> =>
            apiGet(`${PROJECT}/feature_flags/my_flags${encodeParams(params, '?')}`, options),
        evaluationReasons: <T = unknown>(
            distinctId: string,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<T>> =>
            apiGet<T>(
                `${PROJECT}/feature_flags/evaluation_reasons${encodeParams({ distinct_id: distinctId }, '?')}`,
                options
            ),
    },

    webVitals: {
        get: <T = unknown>(params: { pathname: string }, options: ToolbarApiOptions): Promise<ToolbarApiResult<T>> =>
            apiGet<T>(`${ENVIRONMENT}/web_vitals${encodeParams(params, '?')}`, options),
    },

    eventDefinitions: {
        search: (
            query: string,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<{ results?: EventDefinition[] }>> =>
            apiGet(
                `${PROJECT}/event_definitions/${encodeParams(
                    { search: query, limit: 20, event_type: 'event_custom' },
                    '?'
                )}`,
                options
            ),
    },

    objectMediaPreviews: {
        create: (payload: Record<string, any>, options: ToolbarApiOptions): Promise<ToolbarApiResult<unknown>> =>
            apiPost(`${PROJECT}/object_media_previews/`, payload, options),
    },

    elementStats: {
        list: (
            params: Record<string, any>,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<PaginatedResponse<ElementsEventType>>> =>
            apiGet(`/api/element/stats/${encodeParams(params, '?')}`, options),
        // Pagination URLs come from a response body — pinned to the uiHost/apiHost origin.
        page: (
            url: string,
            options: ToolbarApiOptions
        ): Promise<ToolbarApiResult<PaginatedResponse<ElementsEventType>>> =>
            apiGet(url, { ...options, urlConstruction: 'use-as-provided' }),
    },
}

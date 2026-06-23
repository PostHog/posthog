import { combineUrl, encodeParams } from 'kea-router'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'

import { withTokenRefresh } from './toolbarAuth'
import { toolbarConfigLogic } from './toolbarConfigLogic'
import { safeFetch } from './utils'

/**
 * Low-level authenticated transport for the toolbar — the single place that knows how
 * to attach the OAuth bearer, refresh it on 401, clear the session on 403, and emit
 * per-request telemetry. It returns a raw `Response`.
 *
 * Prefer `toolbarApi` (`get`/`post`/`patch`/`delete`) for data requests: it builds on
 * this primitive and adds consistent failure handling, observability, and opt-in toasts.
 * Reach for `toolbarFetch` directly only when you genuinely need the raw `Response` and
 * cannot use `toolbarApi` — currently the dual-context shared logics (`heatmapDataLogic`,
 * `hedgehogModeLogic`) that interleave authenticated toolbar requests with unauthenticated
 * `fetch` and share one response-handling branch across both. Keeping this module free of
 * `lemonToast` (and therefore out of `toolbarApi`'s import graph) also lets those widely
 * imported logics depend on the transport without pulling the toast layer into test setup.
 */
export async function toolbarFetch(
    url: string,
    method: string = 'GET',
    payload?: Record<string, any> | FormData,
    /*
     allows caller to control how the provided URL is altered before use
     if "full" then the payload and URL are taken apart and reconstructed
     if "use-as-provided" then the URL is used as-is, and the payload is not used
     this is because the heatmapLogic needs more control over how the query parameters are constructed
    */
    urlConstruction: 'full' | 'use-as-provided' = 'full'
): Promise<Response> {
    const logic = toolbarConfigLogic.findMounted()
    const accessToken = logic?.values.accessToken
    const host = logic?.values.uiHost

    if (!accessToken) {
        return new Response(JSON.stringify({ results: [] }), { status: 401 })
    }

    let fullUrl: string
    if (urlConstruction === 'use-as-provided') {
        // Pagination URLs come from response bodies — pin to uiHost (or apiHost, which
        // is where Django's build_absolute_uri() sources its host) so they cannot
        // redirect the Authorization header off-origin. Stub body matches the 401
        // shape above so paginating callers fail gracefully on `results: []`.
        const apiHost = logic?.values.apiHost
        const allowedOrigins = [host, apiHost].filter(Boolean).map((h) => {
            try {
                return new URL(h as string).origin
            } catch {
                return null
            }
        })
        if (allowedOrigins.length === 0) {
            return new Response(JSON.stringify({ results: [], detail: 'no_uihost' }), { status: 400 })
        }
        let got: string
        try {
            got = new URL(url).origin
        } catch {
            return new Response(JSON.stringify({ results: [], detail: 'invalid_url' }), { status: 400 })
        }
        if (!allowedOrigins.includes(got)) {
            toolbarLogger.warn('fetch', 'use-as-provided URL origin not in allowlist', {
                allowed: allowedOrigins,
                got,
            })
            return new Response(JSON.stringify({ results: [], detail: 'origin_mismatch' }), { status: 400 })
        }
        fullUrl = url
    } else {
        const { pathname, searchParams } = combineUrl(url)
        fullUrl = `${host}${pathname}${encodeParams(searchParams, '?')}`
    }

    const isFormData = typeof FormData !== 'undefined' && payload instanceof FormData
    const buildHeaders = (token: string): Record<string, string> => {
        const headers: Record<string, string> = { Authorization: `Bearer ${token}` }
        // Don't set Content-Type for FormData: the browser supplies it with a
        // multipart boundary. Setting it manually would corrupt the body.
        if (payload && !isFormData) {
            headers['Content-Type'] = 'application/json'
        }
        return headers
    }
    // `withTokenRefresh` may replay the same request once with a new token. We intentionally
    // reuse the same FormData instance here: FormData is re-readable (unlike one-shot streams),
    // so both the initial send and the retry can consume it safely.
    const body: BodyInit | undefined = payload
        ? isFormData
            ? (payload as FormData)
            : JSON.stringify(payload)
        : undefined

    const startTime = performance.now()
    let didRetry = false

    let response = await safeFetch(fullUrl, {
        method,
        headers: buildHeaders(accessToken),
        ...(body !== undefined ? { body } : {}),
    })

    response = await withTokenRefresh(response, async (newAccessToken) => {
        didRetry = true
        return await safeFetch(fullUrl, {
            method,
            headers: buildHeaders(newAccessToken),
            ...(body !== undefined ? { body } : {}),
        })
    })

    const durationMs = Math.round(performance.now() - startTime)
    const { pathname } = combineUrl(url)

    toolbarPosthogJS.capture('toolbar api request', {
        method,
        pathname,
        status: response.status,
        duration_ms: durationMs,
        did_token_retry: didRetry,
    })

    if (response.status === 403) {
        // The toolbar can't distinguish "token lost access" from "user switched projects" —
        // both are project-level access failures. Clear tokens and let the user re-auth
        // rather than auto-redirecting to /toolbar_oauth/authorize/ (which would use the
        // session's current team, potentially causing a "Domain not authorized" loop).
        toolbarConfigLogic.actions.tokenExpired()
    }
    return response
}

export interface ToolbarMediaUploadResponse {
    id: string
    image_location: string
    name: string
}

/** Upload media (images) from the toolbar. */
export async function toolbarUploadMedia(file: File): Promise<{ id: string; url: string; fileName: string }> {
    // Fail fast when there's no session to begin with — don't route through
    // toolbarFetch (which would return a stub 401 and trip tokenExpired
    // telemetry / toasts for a user who was never authenticated).
    if (!toolbarConfigLogic.findMounted()?.values.accessToken) {
        throw new Error('Toolbar not authenticated')
    }

    // Route through toolbarFetch so authenticated uploads share the single
    // auth + token-refresh implementation. toolbarFetch sends the bearer to
    // uiHost (validated + token-bound), closing the apiHost-redirect leak.
    const formData = new FormData()
    formData.append('image', file)

    const response = await toolbarFetch('/api/projects/@current/uploaded_media/', 'POST', formData)

    if (response.status === 401) {
        // Session was valid at start but expired and refresh failed.
        toolbarConfigLogic.findMounted()?.actions.tokenExpired()
        throw new Error('Authentication expired')
    }

    if (!response.ok) {
        const errorData = await response.json().catch(() => ({}))
        // toolbarFetch already calls tokenExpired() on 403, so no need to repeat it here.
        throw new Error(errorData.detail || `Upload failed: ${response.status}`)
    }

    const data: ToolbarMediaUploadResponse = await response.json()
    return {
        id: data.id,
        url: data.image_location,
        fileName: data.name,
    }
}

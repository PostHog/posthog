import type { BeforeSendFn } from 'posthog-js'

import { ApiError } from './api-error'

/**
 * DRF's `NotAuthenticated` default detail (see `rest_framework.exceptions.NotAuthenticated`).
 * The backend returns this with a 401 whenever an authenticated request arrives without any
 * credentials — which happens routinely and expectedly: the app boots and fires authenticated
 * requests before login, after logout, or when a session cookie has quietly expired. These are
 * not actionable bugs, but the frontend throws them as `ApiError`s that get captured as
 * `$exception`s, so they pile into one enormous catch-all error-tracking issue and drown out
 * genuine failures. We drop them before capture.
 */
export const NOT_AUTHENTICATED_DETAIL = 'Authentication credentials were not provided.'

// Loose shape of a posthog-js `$exception` capture event — enough to filter/fingerprint without
// depending on posthog-js internals. `null` is part of the `before_send` contract.
type ExceptionEvent = { event?: string; properties?: Record<string, any> } | null

type ExceptionListEntry = { type?: string; value?: string }

function exceptionList(event: NonNullable<ExceptionEvent>): ExceptionListEntry[] {
    return (event.properties?.$exception_list ?? []) as ExceptionListEntry[]
}

/**
 * Collapse the volatile parts of an endpoint path so requests to the same route but different
 * resources share a fingerprint — e.g. `GET /api/projects/123/insights/abc-def` and
 * `GET /api/projects/456/insights/ghi-jkl` both become `GET /api/projects/:id/insights/:id`.
 */
export function normalizeEndpointForFingerprint(endpoint?: string | null): string {
    if (!endpoint) {
        return ''
    }
    return endpoint
        .split('?')[0] // drop any query string
        .replace(/\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '/:uuid') // uuids
        .replace(/\/\d+/g, '/:id') // numeric ids
        .replace(/\/[A-Za-z0-9_-]{16,}/g, '/:id') // short ids / opaque tokens
}

/**
 * Fingerprint an ApiError by status code and endpoint, so genuine API failures group by *what*
 * failed rather than collapsing under the shared `new ApiError` stack frame in `api-error.ts`.
 * Passed to `posthog.captureException` at capture sites that hold the error object (see
 * `initKea.ts`). e.g. `"API 403 GET /api/projects/:id/insights/:id"`.
 */
export function apiErrorFingerprint(error: ApiError): string {
    const status = error.status ?? 'error'
    const endpoint = normalizeEndpointForFingerprint(error.endpoint)
    return `API ${status} ${endpoint}`.trim()
}

/**
 * `before_send` filter: drop expected pre-auth / no-credentials 401s (see
 * `NOT_AUTHENTICATED_DETAIL`). Matches on the exception message because it's the only field
 * available client-side — stack frames aren't symbolicated until server-side, so the resolved
 * source path can't be relied on here. Exported for unit testing.
 */
export function dropExpectedAuthExceptions<T extends ExceptionEvent>(event: T): T | null {
    if (!event || event.event !== '$exception') {
        return event
    }
    if (exceptionList(event).some((ex) => ex?.value === NOT_AUTHENTICATED_DETAIL)) {
        return null
    }
    return event
}

/**
 * `before_send` filter: give ApiError `$exception`s that weren't captured with an explicit
 * fingerprint (i.e. truly uncaught ones, which never pass through a capture site that could call
 * `apiErrorFingerprint`) a message-based fingerprint. Status and endpoint live on the Error
 * instance, which posthog-js does not serialize into the event, so the message (DRF `detail`) is
 * the best signal available here — still far better than every ApiError sharing one issue.
 * Exported for unit testing.
 */
export function fingerprintApiErrorExceptions<T extends ExceptionEvent>(event: T): T {
    if (!event || event.event !== '$exception' || !event.properties) {
        return event
    }
    if (event.properties.$exception_fingerprint) {
        // An explicit fingerprint was set at capture time (see `initKea.ts`) — respect it.
        return event
    }
    const apiEx = exceptionList(event).find((ex) => ex?.type === 'ApiError')
    if (apiEx) {
        event.properties.$exception_fingerprint = `ApiError: ${apiEx.value ?? 'unknown'}`
    }
    return event
}

export type ExceptionFilter = (event: ExceptionEvent) => ExceptionEvent

// Always-on filters, applied to every capture in every session.
const baseFilters: ExceptionFilter[] = [dropExpectedAuthExceptions, fingerprintApiErrorExceptions]
// Lifecycle-scoped filters registered by feature logics (e.g. read-only mode) while mounted.
const dynamicFilters = new Set<ExceptionFilter>()

/**
 * Register an additional `before_send` filter for as long as a feature is active. Returns an
 * unregister function to call on teardown. This composes filters instead of the previous pattern
 * of a single owner clobbering `posthog.set_config({ before_send })`, which meant only one
 * concern could filter exceptions at a time.
 */
export function registerExceptionFilter(filter: ExceptionFilter): () => void {
    dynamicFilters.add(filter)
    return () => {
        dynamicFilters.delete(filter)
    }
}

/**
 * The composed `before_send` handler installed at posthog-js init (see `loadPostHogJS`). Runs the
 * always-on base filters followed by any registered dynamic filters, short-circuiting as soon as
 * a filter drops the event.
 */
export const beforeSendExceptionFilter: BeforeSendFn = (event) => {
    let current = event as ExceptionEvent
    for (const filter of baseFilters) {
        if (current === null) {
            return null
        }
        current = filter(current)
    }
    for (const filter of dynamicFilters) {
        if (current === null) {
            return null
        }
        current = filter(current)
    }
    return current as any
}

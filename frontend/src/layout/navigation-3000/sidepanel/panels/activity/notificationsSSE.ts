import api from 'lib/api'
import { ApiError } from 'lib/api-error'

import { InAppNotification } from '~/types'

/**
 * Why a stream ended, so telemetry can tell a genuine failure from background churn.
 *
 * `page_unloading` and `offline` are not reported at all — they are the browser tearing the
 * fetch down for reasons the app neither caused nor can act on, and they otherwise dominate
 * the error volume to the point where a real outage is invisible.
 */
export type SSEDisconnectReason =
    /** The document is going away (reload, close, cross-document navigation). */
    | 'page_unloading'
    /** The browser reports no network at all. */
    | 'offline'
    /** The livestream service rejected the token — retrying the same one cannot help. */
    | 'auth'
    /** Some other non-ok HTTP status on open. */
    | 'server_status'
    /** The request never produced a response. */
    | 'connect_failed'
    /** The stream was live and delivering messages, then the body read failed. */
    | 'stream_dropped'

/**
 * Thrown out of the `onError` hook to unwind fetch-event-source's own retry loop, so reconnects
 * are driven by `retryWithBackoff` in the caller instead. Carrying the classification on the error
 * lets the caller decide whether another attempt is worth making.
 */
export class SSEDisconnectedError extends Error {
    constructor(
        readonly reason: SSEDisconnectReason,
        readonly retryable: boolean
    ) {
        super('SSE disconnected')
        this.name = 'SSEDisconnectedError'
    }
}

/**
 * A cross-document navigation cancels every in-flight fetch, including this stream. `beforeunload`
 * fires before the teardown, so the flag is already set by the time the rejection reaches us.
 * `pagehide` covers the cases `beforeunload` doesn't (bfcache, mobile Safari).
 */
let pageIsUnloading = false
if (typeof window !== 'undefined') {
    const markUnloading = (): void => {
        pageIsUnloading = true
    }
    window.addEventListener('beforeunload', markUnloading)
    // A bfcache restore reuses the document, so an aborted stream there is worth reconnecting.
    window.addEventListener('pagehide', (event) => {
        if (!event.persisted) {
            markUnloading()
        }
    })
}

function classify(error: unknown, streamWasLive: boolean): { reason: SSEDisconnectReason; retryable: boolean } {
    if (pageIsUnloading) {
        return { reason: 'page_unloading', retryable: false }
    }
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
        return { reason: 'offline', retryable: true }
    }
    if (error instanceof ApiError && error.status) {
        // 401/403 mean the live_events_token is stale; a fresh one only arrives with a team reload,
        // so burning the retry budget on it just multiplies requests and telemetry.
        const isAuth = error.status === 401 || error.status === 403
        return { reason: isAuth ? 'auth' : 'server_status', retryable: !isAuth && error.status >= 500 }
    }
    return { reason: streamWasLive ? 'stream_dropped' : 'connect_failed', retryable: true }
}

/** Reasons we deliberately stay silent about — see {@link SSEDisconnectReason}. */
function isReportable(reason: SSEDisconnectReason): boolean {
    return reason !== 'page_unloading' && reason !== 'offline'
}

/**
 * Reasons that mean the stream is gone for good rather than worth another attempt. A document on
 * its way out has nothing left to reconnect for — anything else, including being offline, should
 * still go through the caller's backoff so the panel recovers on its own.
 */
function isCleanShutdown(reason: SSEDisconnectReason): boolean {
    return reason === 'page_unloading'
}

export interface NotificationsSSEHooks {
    onFirstMessage?: () => void
    onError?: (error: unknown, context: { reason: SSEDisconnectReason; streamWasLive: boolean }) => void
}

/**
 * Opens an SSE connection to the livestream notifications endpoint.
 * Returns a promise that rejects when the connection is lost (triggering
 * retryWithBackoff to retry), and resolves only on clean shutdown via the
 * abort signal.
 */
export function connectToNotificationsSSE(
    url: string,
    token: string,
    signal: AbortSignal,
    onNotification: (notification: InAppNotification) => void,
    hooks: NotificationsSSEHooks = {}
): Promise<void> {
    let firstMessageSeen = false
    return api.stream(url, {
        headers: {
            Authorization: `Bearer ${token}`,
        },
        signal,
        onMessage: (event) => {
            if (!firstMessageSeen) {
                firstMessageSeen = true
                hooks.onFirstMessage?.()
            }
            try {
                const notification = JSON.parse(event.data) as InAppNotification
                onNotification(notification)
            } catch {
                // Ignore malformed messages
            }
        },
        onError: (error) => {
            // If the abort was triggered externally (e.g. by the pause-on-hidden
            // disposable in sidePanelNotificationsLogic), surface it as a
            // DOMException AbortError so retryWithBackoff (and the outer .catch on
            // the caller) recognises it as clean cancellation rather than a
            // connection failure to retry. Without this, every visibility-pause
            // cycle would fire spurious livestream_sse_error + livestream_sse_max_errors
            // telemetry and arm an unnecessary sseFocusReconnect listener.
            if (signal.aborted) {
                throw new DOMException('Aborted', 'AbortError')
            }
            // Our own sentinel comes back around: a non-ok status is reported through `onError`
            // from inside fetch-event-source's `onopen`, and the throw below then lands in its
            // catch, which calls `onError` a second time. Rethrowing as-is keeps one disconnect
            // to one report instead of duplicating every status failure.
            if (error instanceof SSEDisconnectedError) {
                throw error
            }
            const { reason, retryable } = classify(error, firstMessageSeen)
            if (isCleanShutdown(reason)) {
                throw new DOMException('Aborted', 'AbortError')
            }
            if (isReportable(reason)) {
                hooks.onError?.(error, { reason, streamWasLive: firstMessageSeen })
            }
            throw new SSEDisconnectedError(reason, retryable)
        },
    })
}

/** Whether `retryWithBackoff` should make another attempt after this failure. */
export function shouldRetrySSE(error: unknown): boolean {
    return !(error instanceof SSEDisconnectedError) || error.retryable
}

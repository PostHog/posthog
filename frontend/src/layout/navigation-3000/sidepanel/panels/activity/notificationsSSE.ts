import api from 'lib/api'

import { InAppNotification } from '~/types'

/** Which server serves the notifications stream. Sent on the `livestream_sse_*` events. */
export type NotificationsSSETransport = 'django' | 'livestream'

export interface NotificationsSSEHooks {
    onFirstMessage?: () => void
    onError?: (error: unknown) => void
    /** The server sent an `end` event because it rotates the stream. Reconnect when the promise resolves. */
    onEnd?: () => void
}

/**
 * Opens an SSE connection to the notifications endpoint: livestream with a bearer
 * token, or the Django endpoint with the session cookie when no token is given.
 * Returns a promise that rejects when the connection is lost (triggering
 * retryWithBackoff to retry), and resolves on clean shutdown via the abort
 * signal or when the server closes the stream.
 */
export function connectToNotificationsSSE(
    url: string,
    token: string | undefined,
    signal: AbortSignal,
    onNotification: (notification: InAppNotification) => void,
    hooks: NotificationsSSEHooks = {}
): Promise<void> {
    let firstMessageSeen = false
    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a URL built at runtime and an unchecked response type. Use a generated function if one covers this endpoint.
    return api.stream(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal,
        onMessage: (event) => {
            if (event.event === 'end') {
                hooks.onEnd?.()
                return
            }
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
            hooks.onError?.(error)
            throw new Error('SSE disconnected')
        },
    })
}

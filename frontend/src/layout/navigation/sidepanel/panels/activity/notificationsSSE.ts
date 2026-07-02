import api from 'lib/api'

import { InAppNotification } from '~/types'

export interface NotificationsSSEHooks {
    onFirstMessage?: () => void
    onError?: (error: unknown) => void
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
            hooks.onError?.(error)
            throw new Error('SSE disconnected')
        },
    })
}

import api from 'lib/api'

import { InAppNotification } from '~/types'

export type NotificationsSSETransport = 'django' | 'livestream'

export type NotificationsSSEOutcome = 'rotate' | 'closed' | 'no_content' | 'aborted'

export interface NotificationsSSEHooks {
    onFirstMessage?: () => void
    onError?: (error: unknown) => void
    onSubscribed?: () => void
}

/**
 * Opens an SSE connection to the livestream notifications endpoint, or to the
 * Django endpoint (session cookie auth) when no token is given.
 * Returns a promise that rejects when the connection is lost (triggering
 * retryWithBackoff to retry), and resolves with the outcome when the stream
 * ends without an error.
 */
export async function connectToNotificationsSSE(
    url: string,
    token: string | undefined,
    signal: AbortSignal,
    onNotification: (notification: InAppNotification) => void,
    hooks: NotificationsSSEHooks = {}
): Promise<NotificationsSSEOutcome> {
    let firstMessageSeen = false
    let outcome: NotificationsSSEOutcome = 'closed'
    // nosemgrep: prefer-codegen-api -- Legacy raw API call with a URL built at runtime and an unchecked response type. Use a generated function if one covers this endpoint.
    await api.stream(url, {
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
        signal,
        // Livestream sends no `ready` event, so an open response is the nearest signal that it subscribed.
        onOpen: token ? () => hooks.onSubscribed?.() : undefined,
        onNoContent: () => {
            outcome = 'no_content'
        },
        onMessage: (event) => {
            if (event.event === 'end') {
                outcome = 'rotate'
                return
            }
            if (event.event === 'ready') {
                hooks.onSubscribed?.()
                return
            }
            // fetch-event-source dispatches an empty message for the blank line after a `: heartbeat` comment.
            if (!event.event && !event.data) {
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
    return signal.aborted ? 'aborted' : outcome
}

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
            hooks.onError?.(error)
            throw new Error('SSE disconnected')
        },
    })
}

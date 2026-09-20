import type { DisposablesManager } from 'kea-disposables'

import { NetworkError, isAbortError } from 'lib/api'
import { retryWithBackoff } from 'lib/utils/async'

/**
 * The browser gave up on the request instead of the server answering it, so there is no HTTP
 * status to read and the endpoint itself is healthy. The account detail page starts several
 * requests at once, so one dropped connection settles every panel into an error state at the same
 * time unless each loader tells this apart from a real API failure.
 */
export function isDroppedRequest(error: unknown): boolean {
    return isAbortError(error) || error instanceof NetworkError
}

/**
 * Runs `load`, and repeats it when the browser drops the request. A connection that comes back
 * within a couple of seconds recovers here, so the panel never shows the user an error.
 */
export async function loadWithRetry<T>(load: () => Promise<T>): Promise<T> {
    return await retryWithBackoff(load, {
        maxAttempts: 3,
        initialDelayMs: 500,
        backoffMultiplier: 3,
        // `navigating` means the document is on its way out, so the response has nowhere to land.
        shouldRetry: (error) => error instanceof NetworkError && error.reason !== 'navigating',
    })
}

/**
 * Runs `reload` when the device comes back online, or when the user returns to the tab. Both are
 * the moment a connection that stayed down long enough to show an error is likely back.
 */
export function reloadOnReconnect(disposables: DisposablesManager, reload: () => void): void {
    disposables.add(
        () => {
            const onVisible = (): void => {
                if (document.visibilityState === 'visible') {
                    reload()
                }
            }
            window.addEventListener('online', reload)
            document.addEventListener('visibilitychange', onVisible)
            return () => {
                window.removeEventListener('online', reload)
                document.removeEventListener('visibilitychange', onVisible)
            }
        },
        'reloadOnReconnect',
        { pauseOnPageHidden: false }
    )
}

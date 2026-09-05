const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'
const RELOAD_GUARD_WINDOW_MS = 20_000

/**
 * Shared guard for the reloads that recover a broken chunk load. A chunk that keeps failing
 * would otherwise reload the page again and again, so every automatic reload stamps the time
 * and the next one only runs when that stamp is old enough.
 */
export function reloadedForChunkFailureRecently(): boolean {
    try {
        const lastReload = Number(window.localStorage.getItem(RELOAD_GUARD_KEY) ?? 0)
        return !!lastReload && Date.now() - lastReload < RELOAD_GUARD_WINDOW_MS
    } catch {
        // localStorage may be unavailable (e.g. Safari private mode) - treat as no prior reload
        return false
    }
}

export function markChunkFailureReload(): void {
    try {
        window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
    } catch {
        // localStorage may throw QuotaExceededError (Safari private mode, full storage).
        // Skip the guard and reload anyway - without the timestamp the worst case is
        // a reload loop, which only happens if the chunk itself keeps failing.
    }
}

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

/**
 * Stamps this reload and returns whether the stamp reached storage. A caller can only count its
 * reloads while the stamp persists, so a false result means the next page load starts again with
 * no record of this one.
 */
export function markChunkFailureReload(): boolean {
    try {
        window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
        return true
    } catch {
        // localStorage may throw QuotaExceededError (Safari private mode, full storage).
        return false
    }
}

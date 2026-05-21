const RELOAD_GUARD_KEY = 'posthog-chunk-reload-at'
const RELOAD_GUARD_WINDOW_MS = 20_000

/**
 * Reloads the page exactly once when a stale-chunk failure is detected, guarded
 * by a localStorage timestamp so we never spin in a reload loop. Shared between
 * `ChunkLoadErrorBoundary` and the pre-React boot path in `index.tsx` so the
 * two recovery routes don't double-reload or fight each other.
 *
 * Returns `true` when a reload was attempted; `false` when the guard kicked in
 * and the caller should surface the error to the user instead.
 */
export function reloadOnceForStaleChunk(reload?: () => void): boolean {
    let lastReload = 0
    try {
        lastReload = Number(window.localStorage.getItem(RELOAD_GUARD_KEY) ?? 0)
    } catch {
        // localStorage may be unavailable (e.g. Safari private mode) - treat as no prior reload
    }
    if (lastReload && Date.now() - lastReload < RELOAD_GUARD_WINDOW_MS) {
        return false
    }
    try {
        window.localStorage.setItem(RELOAD_GUARD_KEY, String(Date.now()))
    } catch {
        // localStorage may throw QuotaExceededError (Safari private mode, full storage).
        // Skip the guard and reload anyway - without the timestamp the worst case is
        // a reload loop, which only happens if the chunk itself keeps failing.
    }
    if (reload) {
        reload()
    } else {
        window.location.reload()
    }
    return true
}

export const __RELOAD_GUARD_KEY_FOR_TESTS = RELOAD_GUARD_KEY

const STORAGE_KEY = 'posthog-chunk-reload-guard'

// A stale-deploy reload followed by a slow scene load can take most of a minute. The
// window must outlast one full cycle, otherwise each new attempt looks like the first
// and the guard reloads forever. Shared by ChunkLoadErrorBoundary and sceneLogic.
const RELOAD_WINDOW_MS = 120_000

// Reload at most this many times in a row before surfacing the error.
const MAX_CONSECUTIVE_RELOADS = 1

interface ReloadGuardState {
    count: number
    at: number
}

function readState(): ReloadGuardState {
    try {
        const raw = window.localStorage.getItem(STORAGE_KEY)
        if (raw) {
            const parsed = JSON.parse(raw)
            if (typeof parsed?.count === 'number' && typeof parsed?.at === 'number') {
                return parsed
            }
        }
    } catch {
        // localStorage unavailable or corrupt (e.g. Safari private mode) - treat as no prior reload
    }
    return { count: 0, at: 0 }
}

/**
 * Records a chunk-load reload attempt and reports whether we should reload again.
 * Counts consecutive attempts inside a window instead of trusting a fixed gap, so a
 * reload cycle slower than the gap still trips the guard rather than looping forever.
 */
export function registerChunkReloadAttempt(now: number): { shouldReload: boolean } {
    const previous = readState()
    const priorCount = now - previous.at < RELOAD_WINDOW_MS ? previous.count : 0
    const count = priorCount + 1
    try {
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ count, at: now }))
    } catch {
        // Can't persist the counter (private mode, quota). Reload once anyway - the worst
        // case is a loop, which only happens if the chunk itself keeps failing.
    }
    return { shouldReload: count <= MAX_CONSECUTIVE_RELOADS }
}

/** Clears the counter after a scene loads, so a later transient failure recovers with a reload. */
export function resetChunkReloadGuard(): void {
    try {
        window.localStorage.removeItem(STORAGE_KEY)
    } catch {
        // localStorage unavailable - nothing to clear
    }
}

const CHUNK_LOAD_RELOAD_MARKER_KEY = 'posthog:chunk-load-reload-at'
export const CHUNK_LOAD_RELOAD_WINDOW_MS = 20_000

export type ChunkLoadRecoveryAction = 'ignore' | 'reload' | 'show-error'

function getSessionStorage(): Storage | null {
    if (typeof window === 'undefined') {
        return null
    }

    try {
        return window.sessionStorage
    } catch {
        return null
    }
}

function getChunkLoadReloadMarker(): number | null {
    const marker = getSessionStorage()?.getItem(CHUNK_LOAD_RELOAD_MARKER_KEY)
    if (!marker) {
        return null
    }

    const parsed = Number(marker)
    return Number.isFinite(parsed) ? parsed : null
}

export function isChunkLoadError(error: unknown): boolean {
    if (!(error instanceof Error)) {
        return false
    }

    return error.name === 'ChunkLoadError' || error.message.includes('Failed to fetch dynamically imported module')
}

export function getChunkLoadRecoveryAction(error: unknown, now = Date.now()): ChunkLoadRecoveryAction {
    if (!isChunkLoadError(error)) {
        return 'ignore'
    }

    const lastReloadAt = getChunkLoadReloadMarker()
    return lastReloadAt && lastReloadAt > now - CHUNK_LOAD_RELOAD_WINDOW_MS ? 'show-error' : 'reload'
}

export function markChunkLoadReloadAttempt(now = Date.now()): void {
    getSessionStorage()?.setItem(CHUNK_LOAD_RELOAD_MARKER_KEY, String(now))
}

export function reloadAfterChunkLoadError(now = Date.now()): void {
    markChunkLoadReloadAttempt(now)
    window.location.reload()
}

export function clearChunkLoadReloadAttempt(): void {
    getSessionStorage()?.removeItem(CHUNK_LOAD_RELOAD_MARKER_KEY)
}

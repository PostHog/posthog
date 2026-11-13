import { unmappedStableChunkSpecifier } from './isChunkLoadError'

/** Only the stable chunk build renders an import map (see posthog/stable_chunks.py). */
export function isStableChunkBuild(): boolean {
    return document.querySelector('script[type="importmap"]') !== null
}

// WebKit fails every `import()` while a navigation to another origin is pending, for example the
// redirect that ends an OAuth authorization. A reload at that moment cancels the navigation, so the
// reload waits this long after the page last began to unload. If the navigation completes, the
// page is gone before the reload runs.
const PENDING_NAVIGATION_GRACE_MS = 10_000
let lastBeforeUnloadAt: number | null = null

// Firefox keeps a page with a `beforeunload` listener out of its back/forward cache, so only WebKit gets one.
// The check matches `isWebKitBrowser` in lib/utils/dom. An import of that file would add it to the entry chunk.
const isWebKit =
    typeof navigator !== 'undefined' &&
    (navigator.vendor === 'Apple Computer, Inc.' || /iPad|iPhone|iPod/.test(navigator.userAgent))

if (typeof window !== 'undefined' && isWebKit) {
    window.addEventListener('beforeunload', () => {
        lastBeforeUnloadAt = Date.now()
    })
}

function afterPendingNavigation(reload: () => void): void {
    const waitMs = lastBeforeUnloadAt === null ? 0 : lastBeforeUnloadAt + PENDING_NAVIGATION_GRACE_MS - Date.now()
    if (waitMs > 0) {
        // A later unload moves the deadline, so the timer checks again before it reloads.
        window.setTimeout(() => afterPendingNavigation(reload), waitMs)
    } else {
        reload()
    }
}

/**
 * Reloads the page after a chunk failed to load. On the stable build, a plain reload gets the same
 * import map and fails again while a new stable chunk is not reachable, so the reload asks for the
 * default build. The server always serves the default build for ?stable_chunks=fallback and stores
 * no choice for it, so this cannot loop, and the next page load tries the stable build again.
 * The reload names a specifier that the import map did not hold, so the server can tell a page
 * whose import map misses a chunk apart from a chunk that failed to load.
 */
export function reloadAfterChunkLoadError(error: unknown): void {
    afterPendingNavigation(() => reloadOnWorkingBuild(error))
}

function reloadOnWorkingBuild(error: unknown): void {
    if (!isStableChunkBuild()) {
        window.location.reload()
        return
    }
    const url = new URL(window.location.href)
    url.searchParams.set('stable_chunks', 'fallback')
    const unmapped = unmappedStableChunkSpecifier(error)
    if (unmapped) {
        url.searchParams.set('stable_chunks_unmapped', unmapped)
    }
    window.location.replace(url.toString())
}

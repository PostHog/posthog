/** Only the stable chunk build renders an import map (see posthog/stable_chunks.py). */
export function isStableChunkBuild(): boolean {
    return document.querySelector('script[type="importmap"]') !== null
}

/**
 * Reloads the page after a chunk failed to load. On the stable build, a plain reload gets the same
 * import map and fails again while a new stable chunk is not reachable, so the reload asks for the
 * default build. The server always serves the default build for ?stable_chunks=fallback and stores
 * no choice for it, so this cannot loop, and the next page load tries the stable build again.
 */
export function reloadAfterChunkLoadError(): void {
    if (!isStableChunkBuild()) {
        window.location.reload()
        return
    }
    const url = new URL(window.location.href)
    url.searchParams.set('stable_chunks', 'fallback')
    window.location.replace(url.toString())
}

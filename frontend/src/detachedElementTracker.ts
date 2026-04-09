const MEMLENS_LIB_URL = 'https://unpkg.com/@memlab/lens@2.0.1/dist/memlens.lib.bundle.min.js'
const MEMLENS_SRI_HASH = 'sha384-X+xkQgJKrxSJJHXfLZ2rZ5dEiybkHcMfqbNRa9YHq3JCFqkg/KY8UJJRcaQqPk03'
const SCAN_INTERVAL_MS = 30_000
const TOP_N = 10
const IDLE_TIMEOUT_MS = 5_000

interface Capturable {
    capture: (event: string, properties?: Record<string, unknown>) => void
}

interface MemLensScanResult {
    totalElements: number
    totalDetachedElements: number
    detachedComponentToFiberNodeCount: Map<string, number>
    componentToFiberNodeCount: Map<string, number>
    start: number
    end: number
}

interface MemLensScanner {
    subscribe: (callback: (result: MemLensScanResult) => void) => () => void
    start: () => void
    stop: () => void
    dispose: () => void
}

interface MemLensGlobal {
    createReactMemoryScan: (options: { scanIntervalMs?: number; trackEventListenerLeaks?: boolean }) => MemLensScanner
}

declare global {
    interface Window {
        MemLens?: MemLensGlobal
    }
}

export function mapToTopN(map: Map<string, number>, limit: number): Record<string, number> {
    const entries = Array.from(map.entries())
    entries.sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    const result: Record<string, number> = {}
    for (let i = 0; i < Math.min(entries.length, limit); i++) {
        result[entries[i][0]] = entries[i][1]
    }
    return result
}

function loadMemLensScript(): Promise<void> {
    return new Promise((resolve, reject) => {
        const script = document.createElement('script')
        script.src = MEMLENS_LIB_URL
        script.integrity = MEMLENS_SRI_HASH
        script.crossOrigin = 'anonymous'
        script.onload = () => resolve()
        script.onerror = () => reject(new Error('Failed to load MemLens script'))
        document.head.appendChild(script)
    })
}

function requestIdleCallbackCompat(callback: () => void, timeout: number): void {
    if ('requestIdleCallback' in window) {
        window.requestIdleCallback(callback, { timeout })
    } else {
        setTimeout(callback, timeout)
    }
}

let initialized = false

export function startDetachedElementTracking(posthog: Capturable): void {
    if (initialized) {
        return
    }
    initialized = true

    requestIdleCallbackCompat(() => {
        loadMemLensScript()
            .then(() => {
                if (!window.MemLens) {
                    console.warn('[detachedElementTracker] MemLens global not found after script load')
                    return
                }

                const scan = window.MemLens.createReactMemoryScan({
                    scanIntervalMs: SCAN_INTERVAL_MS,
                    trackEventListenerLeaks: false,
                })

                scan.subscribe((result) => {
                    posthog.capture('detached_elements', {
                        total_elements: result.totalElements,
                        detached_elements: result.totalDetachedElements,
                        detached_components: mapToTopN(result.detachedComponentToFiberNodeCount, TOP_N),
                        all_components: mapToTopN(result.componentToFiberNodeCount, TOP_N),
                        scan_duration_ms: Math.round(result.end - result.start),
                        current_path: window.location.pathname,
                    })
                })

                function onVisibilityChange(): void {
                    if (document.hidden) {
                        scan.stop()
                    } else {
                        scan.start()
                    }
                }

                document.addEventListener('visibilitychange', onVisibilityChange)

                if (!document.hidden) {
                    scan.start()
                }

                window.addEventListener('beforeunload', () => {
                    scan.stop()
                    scan.dispose()
                    document.removeEventListener('visibilitychange', onVisibilityChange)
                })
            })
            .catch(() => {
                console.warn('[detachedElementTracker] Failed to load MemLens, detached element tracking disabled')
            })
    }, IDLE_TIMEOUT_MS)
}

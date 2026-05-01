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

export function shouldCaptureDetachedElements(currentCount: number, previousCount: number | null): boolean {
    if (currentCount === 0) {
        return false
    }
    if (previousCount === null) {
        return true
    }
    return currentCount !== previousCount
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

function requestIdleCallbackCompat(callback: () => void | Promise<void>, timeout: number): void {
    if ('requestIdleCallback' in window) {
        window.requestIdleCallback(callback, { timeout })
    } else {
        setTimeout(callback, timeout)
    }
}

let state: 'idle' | 'loading' | 'ready' = 'idle'

export function startDetachedElementTracking(posthog: Capturable): void {
    if (state !== 'idle') {
        return
    }
    state = 'loading'

    requestIdleCallbackCompat(async () => {
        try {
            const memlens = await import('@memlab/lens/dist/memlens.lib.bundle.js')
            const createReactMemoryScan =
                memlens.createReactMemoryScan ??
                (memlens as unknown as { default: typeof memlens }).default?.createReactMemoryScan
            if (!createReactMemoryScan) {
                throw new Error('createReactMemoryScan not found in MemLens exports')
            }

            state = 'ready'

            const scan: MemLensScanner = createReactMemoryScan({
                scanIntervalMs: SCAN_INTERVAL_MS,
                trackEventListenerLeaks: false,
            })

            let previousDetachedCount: number | null = null

            scan.subscribe((result) => {
                if (!shouldCaptureDetachedElements(result.totalDetachedElements, previousDetachedCount)) {
                    previousDetachedCount = result.totalDetachedElements
                    return
                }
                previousDetachedCount = result.totalDetachedElements

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
                    previousDetachedCount = null
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
        } catch {
            state = 'idle'
            console.warn('[detachedElementTracker] Failed to load MemLens, detached element tracking disabled')
        }
    }, IDLE_TIMEOUT_MS)
}

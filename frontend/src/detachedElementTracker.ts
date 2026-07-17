import type { MemLensScanner } from '@memlab/lens/dist/memlens.lib.bundle.js'

import { getAppContext } from 'lib/utils/getAppContext'

const SCAN_INTERVAL_MS = 30_000
const TOP_N = 10
const IDLE_TIMEOUT_MS = 5_000

interface Capturable {
    capture: (event: string, properties?: Record<string, unknown>) => void
}

export interface DetachedElementTrackingState {
    currentPath: string | null
    previousPath: string | null
    previousDetachedCount: number | null
    routeBaselineDetachedCount: number | null
    routeFirstObservedAt: number | null
}

interface DetachedElementTrackingContext {
    detachedElementsDelta: number | null
    nextState: DetachedElementTrackingState
    pathChanged: boolean
    previousPath: string | null
    routeAgeMs: number
    routeBaselineDetachedElements: number
    routeDetachedElementsDelta: number
}

export function createDetachedElementTrackingState(): DetachedElementTrackingState {
    return {
        currentPath: null,
        previousPath: null,
        previousDetachedCount: null,
        routeBaselineDetachedCount: null,
        routeFirstObservedAt: null,
    }
}

export function getDetachedElementTrackingContext(
    state: DetachedElementTrackingState,
    currentCount: number,
    currentPath: string,
    observedAt: number
): DetachedElementTrackingContext {
    const pathChanged = state.currentPath !== currentPath
    const routeBaselineDetachedElements = pathChanged
        ? (state.previousDetachedCount ?? currentCount)
        : (state.routeBaselineDetachedCount ?? currentCount)
    const routeFirstObservedAt = pathChanged ? observedAt : (state.routeFirstObservedAt ?? observedAt)
    const previousPath = pathChanged ? state.currentPath : state.previousPath

    return {
        detachedElementsDelta: state.previousDetachedCount === null ? null : currentCount - state.previousDetachedCount,
        pathChanged,
        previousPath,
        routeAgeMs: observedAt - routeFirstObservedAt,
        routeBaselineDetachedElements,
        routeDetachedElementsDelta: currentCount - routeBaselineDetachedElements,
        nextState: {
            currentPath,
            previousPath,
            previousDetachedCount: currentCount,
            routeBaselineDetachedCount: routeBaselineDetachedElements,
            routeFirstObservedAt,
        },
    }
}

export function shouldCaptureDetachedElements(
    currentCount: number,
    previousCount: number | null,
    pathChanged: boolean = false
): boolean {
    if (currentCount === 0) {
        return false
    }
    if (previousCount === null) {
        return true
    }
    return pathChanged || currentCount !== previousCount
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

            const scan = createReactMemoryScan({
                scanIntervalMs: SCAN_INTERVAL_MS,
                trackEventListenerLeaks: false,
            })

            let trackingState = createDetachedElementTrackingState()

            scan.subscribe((result) => {
                const currentPath = window.location.pathname
                const trackingContext = getDetachedElementTrackingContext(
                    trackingState,
                    result.totalDetachedElements,
                    currentPath,
                    Date.now()
                )

                if (
                    !shouldCaptureDetachedElements(
                        result.totalDetachedElements,
                        trackingState.previousDetachedCount,
                        trackingContext.pathChanged
                    )
                ) {
                    trackingState = trackingContext.nextState
                    return
                }
                trackingState = trackingContext.nextState

                posthog.capture('detached_elements', {
                    total_elements: result.totalElements,
                    detached_elements: result.totalDetachedElements,
                    detached_elements_delta: trackingContext.detachedElementsDelta,
                    detached_components: mapToTopN(result.detachedComponentToFiberNodeCount, TOP_N),
                    all_components: mapToTopN(result.componentToFiberNodeCount, TOP_N),
                    scan_duration_ms: Math.round(result.end - result.start),
                    current_path: currentPath,
                    previous_path: trackingContext.previousPath,
                    route_changed: trackingContext.pathChanged,
                    route_age_ms: trackingContext.routeAgeMs,
                    route_baseline_detached_elements: trackingContext.routeBaselineDetachedElements,
                    route_detached_elements_delta: trackingContext.routeDetachedElementsDelta,
                })
            })

            function onVisibilityChange(): void {
                if (document.hidden) {
                    scan.stop()
                } else {
                    trackingState = createDetachedElementTrackingState()
                    scan.start()
                }
            }

            document.addEventListener('visibilitychange', onVisibilityChange)

            if (getAppContext()?.preflight?.is_debug) {
                exposeLeakHunterDevHelpers(scan)
            }

            if (!document.hidden) {
                scan.start()
            }

            window.addEventListener('beforeunload', () => {
                scan.stop()
                scan.dispose()
                delete (window as unknown as { __leakHunter?: unknown }).__leakHunter
                document.removeEventListener('visibilitychange', onVisibilityChange)
            })
        } catch {
            state = 'idle'
            console.warn('[detachedElementTracker] Failed to load MemLens, detached element tracking disabled')
        }
    }, IDLE_TIMEOUT_MS)
}

interface LeakHunterScanSummary {
    totalElements: number
    totalDetachedElements: number
    detachedComponents: Record<string, number>
}

interface LeakHunterDetachedElementSummary {
    i: number
    tag?: string
    id?: string
    classes?: string | null
    components?: string[]
}

// Dev-only console helpers for hunting detached-DOM retainers. The convenience
// accessors (`el(i)`, `detached()`) deref WeakRefs on demand rather than holding
// elements; `scanner` is the raw MemLens instance and keeps its own tracking state.
function exposeLeakHunterDevHelpers(scan: MemLensScanner): void {
    const leakHunter = {
        scanner: scan,
        scan: (): LeakHunterScanSummary => {
            const result = scan.scan()
            return {
                totalElements: result.totalElements,
                totalDetachedElements: result.totalDetachedElements,
                detachedComponents: mapToTopN(result.detachedComponentToFiberNodeCount, 50),
            }
        },
        detached: (limit: number = 50): LeakHunterDetachedElementSummary[] =>
            scan
                .getDetachedDOMInfo()
                .slice(0, limit)
                .map((info, i) => {
                    const el = info.element.deref()
                    return {
                        i,
                        tag: el?.tagName,
                        id: el?.id,
                        classes: el?.getAttribute('class'),
                        components: info.componentStack?.slice(0, 10) ?? undefined,
                    }
                }),
        el: (i: number): Element | undefined => scan.getDetachedDOMInfo()[i]?.element.deref(),
    }
    ;(window as unknown as { __leakHunter?: typeof leakHunter }).__leakHunter = leakHunter
    console.info('[leak-hunter] window.__leakHunter ready')
}

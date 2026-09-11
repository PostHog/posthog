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
    previousDetachedCount: number | null
    previousPersistedCount: number | null
    routeBaselineDetachedCount: number | null
    routeBaselinePersistedCount: number | null
}

interface DetachedElementTrackingContext {
    detachedElementsDelta: number | null
    nextState: DetachedElementTrackingState
    pathChanged: boolean
    routeBaselineDetachedElements: number
    routeDetachedElementsDelta: number
    routeBaselinePersistedElements: number
    routePersistedElementsDelta: number
}

export function createDetachedElementTrackingState(): DetachedElementTrackingState {
    return {
        currentPath: null,
        previousDetachedCount: null,
        previousPersistedCount: null,
        routeBaselineDetachedCount: null,
        routeBaselinePersistedCount: null,
    }
}

export function getDetachedElementTrackingContext(
    state: DetachedElementTrackingState,
    currentCount: number,
    currentPath: string,
    persistedCount: number
): DetachedElementTrackingContext {
    const pathChanged = state.currentPath !== null && state.currentPath !== currentPath
    const routeBaselineDetachedElements = pathChanged
        ? currentCount
        : (state.routeBaselineDetachedCount ?? currentCount)
    const routeBaselinePersistedElements = pathChanged
        ? persistedCount
        : (state.routeBaselinePersistedCount ?? persistedCount)

    return {
        detachedElementsDelta: state.previousDetachedCount === null ? null : currentCount - state.previousDetachedCount,
        pathChanged,
        routeBaselineDetachedElements,
        routeDetachedElementsDelta: currentCount - routeBaselineDetachedElements,
        routeBaselinePersistedElements,
        routePersistedElementsDelta: persistedCount - routeBaselinePersistedElements,
        nextState: {
            currentPath,
            previousDetachedCount: currentCount,
            previousPersistedCount: persistedCount,
            routeBaselineDetachedCount: routeBaselineDetachedElements,
            routeBaselinePersistedCount: routeBaselinePersistedElements,
        },
    }
}

/** One entry of MemLens's detached-DOM report, narrowed to what persistence measurement reads. */
export interface DetachedElementRef {
    element: { deref: () => Element | undefined }
    componentStack?: readonly string[] | null
}

export interface DetachedPersistence {
    persistedCount: number
    persistedComponents: Map<string, number>
    /** Feed back in as `seenPreviously` on the next scan. A WeakSet, so measuring retention cannot cause it. */
    seenNow: WeakSet<Element>
}

/** Split the detached elements that outlived a scan interval from the ones that are only pending collection.
 *
 *  A scan counts every element detached from the document. Most of those are ordinary garbage the collector
 *  has not reached yet, and a page cannot force a collection. So a single count cannot tell a route that
 *  retains DOM apart from a route that merely happened to be open while another route's garbage was pending.
 *  That is why a route's total tracks how much the session navigated rather than what the route holds onto.
 *  An element still detached at the next scan has survived at least one collection opportunity, which makes
 *  it far more likely to be genuinely retained. */
export function measureDetachedPersistence(
    detached: readonly DetachedElementRef[],
    seenPreviously: WeakSet<Element>
): DetachedPersistence {
    const seenNow = new WeakSet<Element>()
    const persistedComponents = new Map<string, number>()
    let persistedCount = 0

    for (const info of detached) {
        const element = info.element.deref()
        if (!element) {
            continue
        }
        seenNow.add(element)
        if (!seenPreviously.has(element)) {
            continue
        }
        persistedCount++
        // The head of the stack, which is what MemLens itself reports as an element's component name.
        const component = info.componentStack?.[0]
        if (component) {
            persistedComponents.set(component, (persistedComponents.get(component) ?? 0) + 1)
        }
    }

    return { persistedCount, persistedComponents, seenNow }
}

export function shouldCaptureDetachedElements(
    currentCount: number,
    previousCount: number | null,
    persistedCount: number,
    previousPersistedCount: number | null
): boolean {
    if (currentCount === 0) {
        return false
    }
    if (previousCount === null) {
        return true
    }
    // A steady leak holds the total still while its elements survive scan after scan, so gating on
    // the total alone would drop every scan that carries a persisted count.
    return currentCount !== previousCount || persistedCount !== previousPersistedCount
}

/** Drop the persistence series while keeping the whole-tab series intact.
 *
 *  MemLens's `stop()` discards its tracked element references, so a scanner restarted after the tab
 *  was hidden begins a new series from nothing. A persisted count is a comparison against the
 *  previous scan, so its baseline has to restart too, or a route delta is measured against a series
 *  that no longer exists. The detached totals are re-derived from a fresh walk on every scan, so
 *  their route baseline stays valid across the restart. */
export function restartPersistenceSeries(state: DetachedElementTrackingState): DetachedElementTrackingState {
    return {
        ...state,
        previousDetachedCount: null,
        previousPersistedCount: null,
        routeBaselinePersistedCount: null,
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
            let elementsDetachedAtLastScan = new WeakSet<Element>()

            scan.subscribe((result) => {
                const currentPath = window.location.pathname
                const persistence = measureDetachedPersistence(scan.getDetachedDOMInfo(), elementsDetachedAtLastScan)
                elementsDetachedAtLastScan = persistence.seenNow

                const trackingContext = getDetachedElementTrackingContext(
                    trackingState,
                    result.totalDetachedElements,
                    currentPath,
                    persistence.persistedCount
                )

                const shouldCapture = shouldCaptureDetachedElements(
                    result.totalDetachedElements,
                    trackingState.previousDetachedCount,
                    persistence.persistedCount,
                    trackingState.previousPersistedCount
                )
                if (!shouldCapture) {
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
                    path_changed_at_scan: trackingContext.pathChanged,
                    path_change_baseline_detached_elements: trackingContext.routeBaselineDetachedElements,
                    detached_elements_delta_since_path_change: trackingContext.routeDetachedElementsDelta,
                    detached_elements_persisted: persistence.persistedCount,
                    detached_components_persisted: mapToTopN(persistence.persistedComponents, TOP_N),
                    path_change_baseline_persisted_elements: trackingContext.routeBaselinePersistedElements,
                    detached_elements_persisted_delta_since_path_change: trackingContext.routePersistedElementsDelta,
                })
            })

            function onVisibilityChange(): void {
                if (document.hidden) {
                    scan.stop()
                } else {
                    elementsDetachedAtLastScan = new WeakSet()
                    trackingState = restartPersistenceSeries(trackingState)
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

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
    scan: () => Omit<MemLensScanResult, 'start' | 'end'>
    getDetachedDOMInfo: () => Array<{ element: WeakRef<Element> }>
}

interface DevHealth {
    js_heap_used_mb: number | null
    js_heap_total_mb: number | null
    js_heap_limit_mb: number | null
    dom_node_count: number
    document_count: number
    iframe_count: number
    canvas_count: number
    svg_count: number
    image_count: number
    tab_age_seconds: number
    listeners_per_node: number | null
}

const tabLoadedAt = typeof performance !== 'undefined' ? performance.now() : Date.now()

export function collectDevHealth(detachedReactCount: number, totalReactCount: number): DevHealth {
    const m = (
        performance as unknown as {
            memory?: { usedJSHeapSize: number; totalJSHeapSize: number; jsHeapSizeLimit: number }
        }
    ).memory
    const dom = document.getElementsByTagName('*').length
    const reactNodes = totalReactCount + detachedReactCount
    return {
        js_heap_used_mb: m ? +(m.usedJSHeapSize / 1024 / 1024).toFixed(1) : null,
        js_heap_total_mb: m ? +(m.totalJSHeapSize / 1024 / 1024).toFixed(1) : null,
        js_heap_limit_mb: m ? +(m.jsHeapSizeLimit / 1024 / 1024).toFixed(1) : null,
        dom_node_count: dom,
        document_count: document.querySelectorAll('html').length,
        iframe_count: document.querySelectorAll('iframe').length,
        canvas_count: document.querySelectorAll('canvas').length,
        svg_count: document.querySelectorAll('svg').length,
        image_count: document.querySelectorAll('img').length,
        tab_age_seconds: Math.round(
            ((typeof performance !== 'undefined' ? performance.now() : Date.now()) - tabLoadedAt) / 1000
        ),
        listeners_per_node: reactNodes > 0 ? +(dom / reactNodes).toFixed(2) : null,
    }
}

const REACT_FIBER_PREFIXES = ['__reactFiber$', '__reactInternalInstance$']
type FiberLike = { type?: unknown; elementType?: unknown; return?: unknown } | null

function fiberOf(element: Element): FiberLike {
    for (const prefix of REACT_FIBER_PREFIXES) {
        const key = Object.getOwnPropertyNames(element).find((k) => k.startsWith(prefix))
        if (key) {
            return (element as unknown as Record<string, FiberLike>)[key]
        }
    }
    return null
}

function nameOfFiber(fiber: FiberLike): string | null {
    if (!fiber) {
        return null
    }
    const t = (fiber.type ?? fiber.elementType) as
        | { displayName?: string; name?: string; render?: { displayName?: string; name?: string } }
        | string
        | undefined
    if (!t || typeof t === 'string') {
        return null
    }
    return t.displayName ?? t.name ?? t.render?.displayName ?? t.render?.name ?? null
}

function nearestNamedAncestor(element: Element): string {
    let fiber = fiberOf(element)
    let depth = 0
    while (fiber && depth < 40) {
        const name = nameOfFiber(fiber)
        if (name) {
            return name
        }
        fiber = (fiber.return as FiberLike) ?? null
        depth += 1
    }
    let node: Node | null = element.parentNode
    let hops = 0
    while (node && hops < 20) {
        if (node instanceof Element) {
            const parentFiber = fiberOf(node)
            let walk = parentFiber
            let d = 0
            while (walk && d < 40) {
                const n = nameOfFiber(walk)
                if (n) {
                    return `via:${n}`
                }
                walk = (walk.return as FiberLike) ?? null
                d += 1
            }
        }
        node = node.parentNode
        hops += 1
    }
    return '<unnamed>'
}

function exposeLeakHunter(scanner: MemLensScanner): void {
    if (process.env.NODE_ENV !== 'development') {
        return
    }
    const w = window as unknown as { __leakHunter?: unknown }
    w.__leakHunter = {
        scan: () => {
            const r = scanner.scan()
            return {
                totalElements: r.totalElements,
                totalDetachedElements: r.totalDetachedElements,
                detachedComponentToFiberNodeCount: Object.fromEntries(r.detachedComponentToFiberNodeCount),
                componentToFiberNodeCount: Object.fromEntries(r.componentToFiberNodeCount),
                path: window.location.pathname,
                takenAt: Date.now(),
            }
        },
        health: () => {
            const r = scanner.scan()
            return collectDevHealth(r.totalDetachedElements, r.totalElements)
        },
        attribute: (): Record<string, number> => {
            scanner.scan()
            const counts: Record<string, number> = {}
            for (const info of scanner.getDetachedDOMInfo()) {
                const el = info.element.deref()
                if (!el) {
                    continue
                }
                const name = nearestNamedAncestor(el)
                counts[name] = (counts[name] ?? 0) + 1
            }
            return counts
        },
        tags: (): Record<string, number> => {
            scanner.scan()
            const counts: Record<string, number> = {}
            for (const info of scanner.getDetachedDOMInfo()) {
                const el = info.element.deref()
                if (!el) {
                    continue
                }
                const tag = el.tagName?.toLowerCase() ?? 'unknown'
                counts[tag] = (counts[tag] ?? 0) + 1
            }
            return counts
        },
        forensics: (limit = 10) => {
            scanner.scan()
            const detachedSet = new Set<Element>()
            for (const info of scanner.getDetachedDOMInfo()) {
                const el = info.element.deref()
                if (el) {
                    detachedSet.add(el)
                }
            }
            const isRoot = (el: Element): boolean => {
                let p: Node | null = el.parentNode
                while (p) {
                    if (p instanceof Element && detachedSet.has(p)) {
                        return false
                    }
                    p = p.parentNode
                }
                return true
            }
            const roots: Array<{
                tag: string
                id?: string
                classes?: string
                childCount: number
                component: string
            }> = []
            for (const el of detachedSet) {
                if (!isRoot(el)) {
                    continue
                }
                const html = el as HTMLElement
                roots.push({
                    tag: html.tagName?.toLowerCase() ?? 'unknown',
                    id: html.id || undefined,
                    classes: typeof html.className === 'string' ? html.className.slice(0, 200) : undefined,
                    childCount: html.querySelectorAll('*').length,
                    component: nearestNamedAncestor(html),
                })
            }
            roots.sort((a, b) => b.childCount - a.childCount)
            return roots.slice(0, limit)
        },
    }
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

            exposeLeakHunter(scan)

            let previousDetachedCount: number | null = null

            scan.subscribe((result) => {
                if (!shouldCaptureDetachedElements(result.totalDetachedElements, previousDetachedCount)) {
                    previousDetachedCount = result.totalDetachedElements
                    return
                }
                previousDetachedCount = result.totalDetachedElements

                const properties: Record<string, unknown> = {
                    total_elements: result.totalElements,
                    detached_elements: result.totalDetachedElements,
                    detached_components: mapToTopN(result.detachedComponentToFiberNodeCount, TOP_N),
                    all_components: mapToTopN(result.componentToFiberNodeCount, TOP_N),
                    scan_duration_ms: Math.round(result.end - result.start),
                    current_path: window.location.pathname,
                }

                // Tag dev runs with extra health context for fast local feedback.
                // Production telemetry shape stays unchanged so existing dashboards
                // and alerts don't move.
                if (process.env.NODE_ENV === 'development') {
                    properties.dev_health = collectDevHealth(result.totalDetachedElements, result.totalElements)
                }

                posthog.capture('detached_elements', properties)
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

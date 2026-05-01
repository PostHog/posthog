import type { Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'

export interface MemorySample {
    t: number
    /** Renderer process RSS in MB. Sum across all chrome renderer processes — for
     * single-tab tests this is dominated by the test page's renderer. Captures
     * off-heap memory (Blink C++ allocations, compositor caches, ArrayBuffers,
     * worker isolates) that V8's `performance.memory` does not. */
    rss_mb: number | null
    /** V8 heap (main thread only). */
    js_heap_used_mb: number | null
    js_heap_total_mb: number | null
    dom_node_count: number
    /** Total event listeners on the page tree. Strong leak indicator — saw +300
     * reclaimed in a single C++ GC sweep on a bloated production tab. */
    js_event_listeners: number
    documents: number
}

/**
 * Sum the RSS of Chrome renderer processes whose command line contains the
 * given discriminator string — typically the Playwright user-data-dir path,
 * which is unique per launched browser. Without filtering we'd include every
 * Chrome / Electron / Steam-Helper renderer on the host.
 *
 * Returns null if `ps` is unavailable or returns no matches.
 */
export function getChromeRendererRssMb(discriminator: string): number | null {
    if (!discriminator) {
        return null
    }
    try {
        const out = execFileSync('ps', ['-axww', '-o', 'pid=,rss=,command='], {
            encoding: 'utf8',
            timeout: 2000,
        })
        let totalKb = 0
        let matches = 0
        for (const line of out.split('\n')) {
            if (!line) {
                continue
            }
            if (!line.includes('--type=renderer')) {
                continue
            }
            if (!line.includes(discriminator)) {
                continue
            }
            const m = line.match(/^\s*(\d+)\s+(\d+)\s/)
            if (!m) {
                continue
            }
            totalKb += Number(m[2])
            matches += 1
        }
        if (matches === 0) {
            return null
        }
        return +(totalKb / 1024).toFixed(1)
    } catch {
        return null
    }
}

export async function sampleMemory(page: Page, rendererDiscriminator: string): Promise<MemorySample> {
    const cdp = await page.context().newCDPSession(page)
    try {
        await cdp.send('Performance.enable').catch(() => undefined)
        const dom = (await cdp.send('Memory.getDOMCounters').catch(() => null)) as {
            documents: number
            nodes: number
            jsEventListeners: number
        } | null
        const perfMetrics = (await cdp.send('Performance.getMetrics').catch(() => null)) as {
            metrics: Array<{ name: string; value: number }>
        } | null
        const m = perfMetrics ? Object.fromEntries(perfMetrics.metrics.map((x) => [x.name, x.value])) : {}

        return {
            t: Date.now(),
            rss_mb: getChromeRendererRssMb(rendererDiscriminator),
            js_heap_used_mb: typeof m.JSHeapUsedSize === 'number' ? +(m.JSHeapUsedSize / 1024 / 1024).toFixed(1) : null,
            js_heap_total_mb:
                typeof m.JSHeapTotalSize === 'number' ? +(m.JSHeapTotalSize / 1024 / 1024).toFixed(1) : null,
            dom_node_count: dom?.nodes ?? 0,
            js_event_listeners: dom?.jsEventListeners ?? 0,
            documents: dom?.documents ?? 0,
        }
    } finally {
        await cdp.detach().catch(() => undefined)
    }
}

export async function forceGc(page: Page): Promise<void> {
    const cdp = await page.context().newCDPSession(page)
    try {
        await cdp.send('HeapProfiler.enable').catch(() => undefined)
        // Twice — single pass often leaves cross-heap refs (V8↔Oilpan) that only
        // a second pass clears.
        await cdp.send('HeapProfiler.collectGarbage').catch(() => undefined)
        await cdp.send('HeapProfiler.collectGarbage').catch(() => undefined)
    } finally {
        await cdp.detach().catch(() => undefined)
    }
}

export function summarise(samples: MemorySample[]): {
    duration_s: number
    rss_growth_mb: number | null
    listeners_growth: number
    dom_growth: number
    js_heap_growth_mb: number | null
    rss_per_minute_mb: number | null
    listeners_per_minute: number | null
} {
    if (samples.length < 2) {
        return {
            duration_s: 0,
            rss_growth_mb: null,
            listeners_growth: 0,
            dom_growth: 0,
            js_heap_growth_mb: null,
            rss_per_minute_mb: null,
            listeners_per_minute: null,
        }
    }
    const first = samples[0]
    const last = samples[samples.length - 1]
    const duration_s = (last.t - first.t) / 1000
    const minutes = duration_s / 60
    const rss = first.rss_mb !== null && last.rss_mb !== null ? +(last.rss_mb - first.rss_mb).toFixed(1) : null
    const heap =
        first.js_heap_used_mb !== null && last.js_heap_used_mb !== null
            ? +(last.js_heap_used_mb - first.js_heap_used_mb).toFixed(1)
            : null
    return {
        duration_s: +duration_s.toFixed(1),
        rss_growth_mb: rss,
        listeners_growth: last.js_event_listeners - first.js_event_listeners,
        dom_growth: last.dom_node_count - first.dom_node_count,
        js_heap_growth_mb: heap,
        rss_per_minute_mb: rss !== null && minutes > 0 ? +(rss / minutes).toFixed(2) : null,
        listeners_per_minute:
            minutes > 0 ? +((last.js_event_listeners - first.js_event_listeners) / minutes).toFixed(1) : null,
    }
}

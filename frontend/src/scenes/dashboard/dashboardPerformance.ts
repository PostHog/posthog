import posthog from 'posthog-js'

import { DashboardPlacement } from '~/types'

// pinned: analytics event name, renaming it breaks insights built on it
export const DASHBOARD_PERFORMANCE_EVENT = 'dashboard performance'
export const DASHBOARD_PERFORMANCE_SAMPLE_RATE = 0.25

const MIN_VISIBLE_MS = 2000
const SCROLL_IDLE_MS = 150
const MEMORY_SAMPLE_INTERVAL_MS = 30_000
const LONG_TASK_BLOCKING_THRESHOLD_MS = 50
const SLOW_FRAME_MS = 1000 / 30
const DASHBOARD_ROOT_SELECTOR = '.dashboard'

// Not yet in lib.dom.d.ts.
interface LongAnimationFrameEntry extends PerformanceEntry {
    blockingDuration: number
}

interface ChromiumPerformanceMemory {
    usedJSHeapSize: number
    jsHeapSizeLimit: number
}

export interface DashboardPerformanceContext {
    dashboardId: number
    placement: DashboardPlacement
    getTileCount: () => number
}

export interface DashboardPerformanceCaptureOptions {
    transport?: 'sendBeacon'
    send_instantly?: boolean
}

/**
 * Collects jank, scroll FPS and JS heap figures for one dashboard view, then sends them as one event.
 */
export class DashboardPerformanceMonitor {
    // Everything observed is page-wide, so a second monitor would count the same jank twice.
    private static active: DashboardPerformanceMonitor | null = null

    private readonly startedAt: number
    private finished = false

    private visibleMs = 0
    private visibleSince: number | null

    private longFrameSource: 'long-animation-frame' | 'longtask' | null = null
    private longFrameCount = 0
    private longFrameTotalMs = 0
    private longFrameMaxMs = 0
    private blockingMs = 0

    private scrollFrameCount = 0
    private scrollMs = 0
    private slowScrollFrameCount = 0
    private worstScrollFrameMs = 0
    private lastScrollFrameAt: number | null = null

    private heapStartBytes: number | null = null
    private heapPeakBytes: number | null = null

    constructor(
        private readonly context: DashboardPerformanceContext,
        now: number = performance.now(),
        visible: boolean = document.visibilityState === 'visible'
    ) {
        this.startedAt = now
        this.visibleSince = visible ? now : null
    }

    static shouldSample(random: number = Math.random()): boolean {
        return random < DASHBOARD_PERFORMANCE_SAMPLE_RATE
    }

    recordLongFrame(durationMs: number, blockingMs: number): void {
        if (this.finished || this.visibleSince === null) {
            return
        }
        this.longFrameCount += 1
        this.longFrameTotalMs += durationMs
        this.longFrameMaxMs = Math.max(this.longFrameMaxMs, durationMs)
        this.blockingMs += blockingMs
    }

    recordScrollFrame(now: number): void {
        if (this.lastScrollFrameAt !== null) {
            const frameMs = now - this.lastScrollFrameAt
            this.scrollFrameCount += 1
            this.scrollMs += frameMs
            this.worstScrollFrameMs = Math.max(this.worstScrollFrameMs, frameMs)
            if (frameMs > SLOW_FRAME_MS) {
                this.slowScrollFrameCount += 1
            }
        }
        this.lastScrollFrameAt = now
    }

    endScrollBurst(now?: number): void {
        // A stall can outlast the idle timer, which then fires before the stalled frame paints.
        if (now !== undefined && this.lastScrollFrameAt !== null && now - this.lastScrollFrameAt > SLOW_FRAME_MS) {
            this.recordScrollFrame(now)
        }
        this.lastScrollFrameAt = null
    }

    recordHeap(memory: ChromiumPerformanceMemory | undefined): void {
        if (!memory) {
            return
        }
        this.heapStartBytes ??= memory.usedJSHeapSize
        this.heapPeakBytes = Math.max(this.heapPeakBytes ?? 0, memory.usedJSHeapSize)
    }

    setVisible(visible: boolean, now: number = performance.now()): void {
        if (visible && this.visibleSince === null) {
            this.visibleSince = now
        } else if (!visible && this.visibleSince !== null) {
            this.visibleMs += now - this.visibleSince
            this.visibleSince = null
            this.endScrollBurst()
        }
    }

    finish(
        now: number = performance.now(),
        memory: ChromiumPerformanceMemory | undefined = readHeap()
    ): Record<string, unknown> | null {
        if (this.finished) {
            return null
        }
        this.finished = true
        this.setVisible(false, now)
        this.recordHeap(memory)
        if (this.visibleMs < MIN_VISIBLE_MS) {
            return null
        }

        const visibleMinutes = this.visibleMs / 60_000
        const round = (value: number): number => Math.round(value)
        return {
            dashboard_id: this.context.dashboardId,
            sample_rate: DASHBOARD_PERFORMANCE_SAMPLE_RATE,
            placement: this.context.placement,
            tile_count: this.context.getTileCount(),
            duration_ms: round(now - this.startedAt),
            visible_ms: round(this.visibleMs),
            long_frame_source: this.longFrameSource,
            long_frame_count: this.longFrameCount,
            long_frame_total_ms: round(this.longFrameTotalMs),
            long_frame_max_ms: round(this.longFrameMaxMs),
            blocking_ms: round(this.blockingMs),
            blocking_ms_per_minute: round(this.blockingMs / visibleMinutes),
            scroll_ms: round(this.scrollMs),
            scroll_frame_count: this.scrollFrameCount,
            scroll_fps: this.scrollMs > 0 ? Math.round((this.scrollFrameCount / this.scrollMs) * 1000 * 10) / 10 : null,
            scroll_slow_frame_ratio:
                this.scrollFrameCount > 0
                    ? Math.round((this.slowScrollFrameCount / this.scrollFrameCount) * 1000) / 1000
                    : null,
            scroll_worst_frame_ms: this.scrollFrameCount > 0 ? round(this.worstScrollFrameMs) : null,
            heap_start_mb: toMegabytes(this.heapStartBytes),
            heap_end_mb: toMegabytes(memory?.usedJSHeapSize ?? null),
            heap_peak_mb: toMegabytes(this.heapPeakBytes),
            heap_limit_mb: toMegabytes(memory?.jsHeapSizeLimit ?? null),
            viewport_width: window.innerWidth,
            viewport_height: window.innerHeight,
            device_pixel_ratio: window.devicePixelRatio,
            device_memory_gb: (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? null,
            hardware_concurrency: navigator.hardwareConcurrency ?? null,
        }
    }

    start(): (options?: DashboardPerformanceCaptureOptions) => void {
        if (DashboardPerformanceMonitor.active) {
            return () => {}
        }
        DashboardPerformanceMonitor.active = this
        const stops: (() => void)[] = [
            () => {
                DashboardPerformanceMonitor.active = null
            },
        ]
        const stopAll = (): void => {
            stops.splice(0).forEach((stop) => stop())
        }

        // Telemetry must never break the dashboard, so a failure here only drops this view's event.
        try {
            this.recordHeap(readHeap())
            const heapTimer = window.setInterval(() => this.recordHeap(readHeap()), MEMORY_SAMPLE_INTERVAL_MS)
            stops.push(() => clearInterval(heapTimer))

            const supported =
                typeof PerformanceObserver !== 'undefined' ? (PerformanceObserver.supportedEntryTypes ?? []) : []
            if (supported.includes('long-animation-frame')) {
                this.longFrameSource = 'long-animation-frame'
                stops.push(
                    observe('long-animation-frame', (entry) =>
                        this.recordLongFrame(entry.duration, (entry as LongAnimationFrameEntry).blockingDuration)
                    )
                )
            } else if (supported.includes('longtask')) {
                this.longFrameSource = 'longtask'
                stops.push(
                    observe('longtask', (entry) =>
                        this.recordLongFrame(
                            entry.duration,
                            Math.max(0, entry.duration - LONG_TASK_BLOCKING_THRESHOLD_MS)
                        )
                    )
                )
            }

            const onVisibilityChange = (): void => this.setVisible(document.visibilityState === 'visible')
            document.addEventListener('visibilitychange', onVisibilityChange)
            stops.push(() => document.removeEventListener('visibilitychange', onVisibilityChange))

            stops.push(this.watchScrolling())
        } catch {
            stopAll()
            this.finished = true
            return () => {}
        }

        return (options) => {
            try {
                stopAll()
                const properties = this.finish()
                if (properties) {
                    posthog.capture(DASHBOARD_PERFORMANCE_EVENT, properties, options)
                }
            } catch {}
        }
    }

    private watchScrolling(): () => void {
        let frameId: number | null = null
        let idleTimer: number | null = null
        let dashboardRoot: Element | null = null

        const tick = (now: number): void => {
            this.recordScrollFrame(now)
            frameId = requestAnimationFrame(tick)
        }
        const stopBurst = (): void => {
            if (frameId !== null) {
                cancelAnimationFrame(frameId)
                frameId = null
            }
            this.endScrollBurst(performance.now())
        }
        const movesDashboard = (target: EventTarget | null): boolean => {
            if (target === document) {
                return true
            }
            if (!dashboardRoot?.isConnected) {
                dashboardRoot = document.querySelector(DASHBOARD_ROOT_SELECTOR)
            }
            return target instanceof Element && !!dashboardRoot && target.contains(dashboardRoot)
        }
        const onScroll = (event: Event): void => {
            if (!movesDashboard(event.target)) {
                return
            }
            if (frameId === null) {
                frameId = requestAnimationFrame(tick)
            }
            if (idleTimer !== null) {
                clearTimeout(idleTimer)
            }
            idleTimer = window.setTimeout(stopBurst, SCROLL_IDLE_MS)
        }

        // The dashboard scrolls inside the scene container, and scroll events do not bubble, so listen in the capture phase.
        document.addEventListener('scroll', onScroll, { capture: true, passive: true })
        return () => {
            document.removeEventListener('scroll', onScroll, { capture: true })
            if (idleTimer !== null) {
                clearTimeout(idleTimer)
            }
            stopBurst()
        }
    }
}

function observe(type: string, onEntry: (entry: PerformanceEntry) => void): () => void {
    const observer = new PerformanceObserver((list) => list.getEntries().forEach(onEntry))
    try {
        observer.observe({ type, buffered: false })
    } catch {
        return () => {}
    }
    return () => {
        observer.takeRecords().forEach(onEntry)
        observer.disconnect()
    }
}

function readHeap(): ChromiumPerformanceMemory | undefined {
    return (performance as Performance & { memory?: ChromiumPerformanceMemory }).memory
}

function toMegabytes(bytes: number | null): number | null {
    return bytes === null ? null : Math.round((bytes / (1024 * 1024)) * 10) / 10
}

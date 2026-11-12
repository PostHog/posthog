import posthog from 'posthog-js'

import { DashboardPlacement } from '~/types'

import { getMountedDashboardTileCount } from './components/dashboardMountedTiles'

// pinned: analytics event name, renaming it breaks insights built on it
export const DASHBOARD_PERFORMANCE_EVENT = 'dashboard performance'
export const DASHBOARD_PERFORMANCE_SAMPLE_RATE = 0.25
// pinned: insights split performance by this value to compare grid implementations
export const DASHBOARD_GRID_ENGINE = 'react-grid-layout'

const MIN_VISIBLE_MS = 2000
// Two 60 Hz frames. A gap longer than this is a dropped frame that a user can see during a drag.
const SLOW_FRAME_MS = 33

// Not yet in lib.dom.d.ts.
interface LongAnimationFrameEntry extends PerformanceEntry {
    blockingDuration: number
}

interface ChromiumPerformanceMemory {
    usedJSHeapSize: number
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
 * Collects main-thread jank and JS heap figures for one dashboard view, then sends them as one event.
 */
export class DashboardPerformanceMonitor {
    // Everything observed is page-wide, so a second monitor would count the same jank twice.
    private static endActiveView: (() => void) | null = null

    private readonly startedAt: number
    private finished = false

    private visibleMs = 0
    private visibleSince: number | null

    private longFrameCount = 0
    private longFrameMaxMs = 0
    private blockingMs = 0

    private heapStartBytes: number | null = null

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
        this.longFrameMaxMs = Math.max(this.longFrameMaxMs, durationMs)
        this.blockingMs += blockingMs
    }

    recordHeapStart(memory: ChromiumPerformanceMemory | undefined): void {
        this.heapStartBytes = memory?.usedJSHeapSize ?? null
    }

    setVisible(visible: boolean, now: number = performance.now()): void {
        if (visible && this.visibleSince === null) {
            this.visibleSince = now
        } else if (!visible && this.visibleSince !== null) {
            this.visibleMs += now - this.visibleSince
            this.visibleSince = null
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
        if (this.visibleMs < MIN_VISIBLE_MS) {
            return null
        }

        return {
            dashboard_id: this.context.dashboardId,
            sample_rate: DASHBOARD_PERFORMANCE_SAMPLE_RATE,
            placement: this.context.placement,
            tile_count: this.context.getTileCount(),
            duration_ms: Math.round(now - this.startedAt),
            visible_ms: Math.round(this.visibleMs),
            long_frame_count: this.longFrameCount,
            long_frame_max_ms: Math.round(this.longFrameMaxMs),
            blocking_ms: Math.round(this.blockingMs),
            blocking_ms_per_minute: Math.round(this.blockingMs / (this.visibleMs / 60_000)),
            heap_start_mb: toMegabytes(this.heapStartBytes),
            heap_end_mb: toMegabytes(memory?.usedJSHeapSize ?? null),
            mounted_tile_count: getMountedDashboardTileCount(),
            dom_node_count: document.getElementsByTagName('*').length,
            grid_engine: DASHBOARD_GRID_ENGINE,
            viewport_width: window.innerWidth,
            viewport_height: window.innerHeight,
            device_memory_gb: (navigator as Navigator & { deviceMemory?: number }).deviceMemory ?? null,
            hardware_concurrency: navigator.hardwareConcurrency ?? null,
        }
    }

    start(): (options?: DashboardPerformanceCaptureOptions) => void {
        // Without the long-animation-frame API the jank figures would read as zero, which looks like a perfect view.
        if (!supportsLongAnimationFrames()) {
            return () => {}
        }
        // The next dashboard mounts before the previous view cleans up, so the new view ends the old one.
        DashboardPerformanceMonitor.endActiveView?.()

        const stops: (() => void)[] = []
        const stopAll = (): void => {
            stops.splice(0).forEach((stop) => stop())
        }
        const report = (options?: DashboardPerformanceCaptureOptions): void => {
            try {
                stopAll()
                const properties = this.finish()
                if (properties) {
                    posthog.capture(DASHBOARD_PERFORMANCE_EVENT, properties, options)
                }
            } catch {}
        }
        DashboardPerformanceMonitor.endActiveView = report
        stops.push(() => {
            if (DashboardPerformanceMonitor.endActiveView === report) {
                DashboardPerformanceMonitor.endActiveView = null
            }
        })

        // Telemetry must never break the dashboard, so a failure here only drops this view's event.
        try {
            this.recordHeapStart(readHeap())

            const onEntry = (entry: PerformanceEntry): void =>
                this.recordLongFrame(entry.duration, (entry as LongAnimationFrameEntry).blockingDuration)
            const observer = new PerformanceObserver((list) => list.getEntries().forEach(onEntry))
            observer.observe({ type: 'long-animation-frame', buffered: false })
            stops.push(() => {
                observer.takeRecords().forEach(onEntry)
                observer.disconnect()
            })

            const onVisibilityChange = (): void => this.setVisible(document.visibilityState === 'visible')
            document.addEventListener('visibilitychange', onVisibilityChange)
            stops.push(() => document.removeEventListener('visibilitychange', onVisibilityChange))
        } catch {
            stopAll()
            this.finished = true
            return () => {}
        }

        return report
    }
}

export interface LayoutGesturePerformance {
    gesture_duration_ms: number
    frame_count: number
    frame_gap_p95_ms: number | null
    frame_gap_max_ms: number | null
    slow_frame_count: number
    release_to_paint_ms: number
    mounted_tile_count: number
    grid_engine: string
}

export class LayoutGestureMonitor {
    private readonly gaps: number[] = []
    private lastFrameAt: number | null = null
    private frameRequest = 0
    private finished = false

    constructor(
        private readonly startedAt: number = performance.now(),
        private readonly requestFrame: (callback: FrameRequestCallback) => number = (callback) =>
            requestAnimationFrame(callback),
        private readonly cancelFrame: (handle: number) => void = (handle) => cancelAnimationFrame(handle)
    ) {
        // The first gap runs from the gesture start, so work that delays the first frame counts as a slow frame.
        this.lastFrameAt = startedAt
    }

    start(): this {
        const onFrame = (frameAt: number): void => {
            this.recordFrame(frameAt)
            this.frameRequest = this.requestFrame(onFrame)
        }
        this.frameRequest = this.requestFrame(onFrame)
        document.addEventListener('visibilitychange', this.onVisibilityChange)
        return this
    }

    recordFrame(frameAt: number): void {
        if (this.lastFrameAt !== null) {
            this.gaps.push(Math.max(0, frameAt - this.lastFrameAt))
        }
        this.lastFrameAt = frameAt
    }

    // A carried tile stays in the gesture while the tab is hidden, and the browser pauses frames for that time.
    private readonly onVisibilityChange = (): void => {
        if (document.visibilityState === 'hidden') {
            this.lastFrameAt = null
        }
    }

    /**
     * Reports after the second frame from release, because the first frame callback runs before the dropped layout paints.
     * Pass the time the stop handler started, so the grid's own drop work counts toward the release.
     */
    finish(report: (performance: LayoutGesturePerformance) => void, releasedAt: number = performance.now()): void {
        if (this.finished) {
            return
        }
        this.cancel()
        this.requestFrame(() =>
            this.requestFrame(() => {
                try {
                    report(this.summarize(releasedAt, performance.now()))
                } catch {}
            })
        )
    }

    cancel(): void {
        this.finished = true
        this.cancelFrame(this.frameRequest)
        document.removeEventListener('visibilitychange', this.onVisibilityChange)
    }

    summarize(releasedAt: number, paintedAt: number): LayoutGesturePerformance {
        const sorted = [...this.gaps].sort((a, b) => a - b)
        return {
            gesture_duration_ms: Math.round(releasedAt - this.startedAt),
            frame_count: this.gaps.length,
            frame_gap_p95_ms: sorted.length ? Math.round(sorted[Math.ceil(sorted.length * 0.95) - 1]) : null,
            frame_gap_max_ms: sorted.length ? Math.round(sorted[sorted.length - 1]) : null,
            slow_frame_count: sorted.filter((gap) => gap > SLOW_FRAME_MS).length,
            release_to_paint_ms: Math.round(paintedAt - releasedAt),
            mounted_tile_count: getMountedDashboardTileCount(),
            grid_engine: DASHBOARD_GRID_ENGINE,
        }
    }
}

function supportsLongAnimationFrames(): boolean {
    return (
        typeof PerformanceObserver !== 'undefined' &&
        (PerformanceObserver.supportedEntryTypes ?? []).includes('long-animation-frame')
    )
}

function readHeap(): ChromiumPerformanceMemory | undefined {
    return (performance as Performance & { memory?: ChromiumPerformanceMemory }).memory
}

function toMegabytes(bytes: number | null): number | null {
    return bytes === null ? null : Math.round((bytes / (1024 * 1024)) * 10) / 10
}

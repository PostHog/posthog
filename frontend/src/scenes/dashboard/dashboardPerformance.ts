import posthog from 'posthog-js'

import { DashboardPlacement } from '~/types'

// pinned: analytics event name, renaming it breaks insights built on it
export const DASHBOARD_PERFORMANCE_EVENT = 'dashboard performance'
export const DASHBOARD_PERFORMANCE_SAMPLE_RATE = 0.25

const MIN_VISIBLE_MS = 2000

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

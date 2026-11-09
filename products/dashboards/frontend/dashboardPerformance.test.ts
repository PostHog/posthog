import posthog from 'posthog-js'

import { DashboardPlacement } from '~/types'

import { DashboardPerformanceMonitor } from './dashboardPerformance'

describe('DashboardPerformanceMonitor', () => {
    const context = { dashboardId: 1, placement: DashboardPlacement.Dashboard, getTileCount: () => 3 }
    const heap = (mb: number): { usedJSHeapSize: number } => ({ usedJSHeapSize: mb * 1024 * 1024 })

    it('reports once and leaves out time and jank from a hidden tab', () => {
        const monitor = new DashboardPerformanceMonitor(context, 0, true)
        monitor.recordHeapStart(heap(100))
        monitor.recordLongFrame(120, 70)
        monitor.setVisible(false, 30_000)
        monitor.recordLongFrame(500, 450)
        monitor.setVisible(true, 90_000)

        expect(monitor.finish(120_000, heap(150))).toMatchObject({
            duration_ms: 120_000,
            visible_ms: 60_000,
            long_frame_count: 1,
            long_frame_max_ms: 120,
            blocking_ms: 70,
            blocking_ms_per_minute: 70,
            heap_start_mb: 100,
            heap_end_mb: 150,
            tile_count: 3,
        })
        expect(monitor.finish(130_000, heap(150))).toBeNull()
    })

    it('skips views too short to measure', () => {
        expect(new DashboardPerformanceMonitor(context, 0, true).finish(500, undefined)).toBeNull()
    })

    it('hands monitoring to the next dashboard when it mounts before the previous view cleans up', () => {
        class FakePerformanceObserver {
            static supportedEntryTypes = ['long-animation-frame']
            observe(): void {}
            disconnect(): void {}
            takeRecords(): PerformanceEntry[] {
                return []
            }
        }
        const originalObserver = globalThis.PerformanceObserver
        globalThis.PerformanceObserver = FakePerformanceObserver as unknown as typeof PerformanceObserver
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        jest.useFakeTimers()
        try {
            const reportFirst = new DashboardPerformanceMonitor({ ...context, dashboardId: 1 }).start()
            jest.advanceTimersByTime(5_000)
            const reportSecond = new DashboardPerformanceMonitor({ ...context, dashboardId: 2 }).start()
            jest.advanceTimersByTime(5_000)
            reportFirst()
            reportSecond()

            expect(capture.mock.calls.map(([, properties]) => properties?.dashboard_id)).toEqual([1, 2])
        } finally {
            jest.useRealTimers()
            capture.mockRestore()
            globalThis.PerformanceObserver = originalObserver
        }
    })
})

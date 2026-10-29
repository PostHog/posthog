import { DashboardPlacement } from '~/types'

import { DashboardPerformanceMonitor } from './dashboardPerformance'

describe('DashboardPerformanceMonitor', () => {
    const context = { dashboardId: 1, placement: DashboardPlacement.Dashboard, getTileCount: () => 3 }
    const heap = (mb: number): { usedJSHeapSize: number; jsHeapSizeLimit: number } => ({
        usedJSHeapSize: mb * 1024 * 1024,
        jsHeapSizeLimit: 4096 * 1024 * 1024,
    })

    it('reports once and leaves out time and jank from a hidden tab', () => {
        const monitor = new DashboardPerformanceMonitor(context, 0, true)
        monitor.recordHeap(heap(100))
        monitor.recordLongFrame(120, 70)
        monitor.setVisible(false, 30_000)
        monitor.recordLongFrame(500, 450)
        monitor.setVisible(true, 90_000)
        monitor.recordScrollFrame(100_000)
        monitor.recordScrollFrame(100_016)
        monitor.recordScrollFrame(100_066)

        expect(monitor.finish(120_000, heap(150))).toMatchObject({
            duration_ms: 120_000,
            visible_ms: 60_000,
            long_frame_count: 1,
            blocking_ms: 70,
            blocking_ms_per_minute: 70,
            scroll_frame_count: 2,
            scroll_worst_frame_ms: 50,
            scroll_slow_frame_ratio: 0.5,
            heap_start_mb: 100,
            heap_peak_mb: 150,
            tile_count: 3,
        })
        expect(monitor.finish(130_000, heap(150))).toBeNull()
    })

    it('skips views too short to measure', () => {
        expect(new DashboardPerformanceMonitor(context, 0, true).finish(500, undefined)).toBeNull()
    })
})

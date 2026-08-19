import { EventType, IncrementalSource } from 'posthog-js/rrweb-types'

import { createSegments, mapSnapshotsToWindowId, type RecordingSnapshot } from '@posthog/replay-shared'

import { eventsForRenderedWindow } from '../render-window'

describe('render-window', () => {
    describe('eventsForRenderedWindow', () => {
        const move = (windowId: number, timestamp: number): RecordingSnapshot =>
            ({
                windowId,
                timestamp,
                type: EventType.IncrementalSnapshot,
                data: { source: IncrementalSource.MouseMove },
            }) as unknown as RecordingSnapshot
        const full = (windowId: number, timestamp: number): RecordingSnapshot =>
            ({ windowId, timestamp, type: EventType.FullSnapshot, data: {} }) as unknown as RecordingSnapshot

        it('drops an interleaving background window so it cannot repaint the frame', () => {
            // Window 1 stays ongoing through +300ms while window 2 interleaves. Feeding window 2's
            // FullSnapshot to the single Replayer would rebuild the DOM to the background tab.
            const snapshots = [full(1, 0), full(2, 50), move(1, 100), move(2, 150), move(1, 300)]
            const segments = createSegments(snapshots, 0, 300, null, mapSnapshotsToWindowId(snapshots))

            const kept = eventsForRenderedWindow(snapshots, segments)

            expect(kept.every((snapshot) => snapshot.windowId === 1)).toBe(true)
            expect(kept.some((snapshot) => snapshot.windowId === 2 && snapshot.type === EventType.FullSnapshot)).toBe(
                false
            )
        })

        it('keeps every event across a sequential window handoff', () => {
            // Window 1 ends before window 2 starts, so both windows genuinely render in turn.
            const snapshots = [full(1, 0), move(1, 100), full(2, 200), move(2, 300)]
            const segments = createSegments(snapshots, 0, 300, null, mapSnapshotsToWindowId(snapshots))

            const kept = eventsForRenderedWindow(snapshots, segments)

            expect(kept).toHaveLength(snapshots.length)
        })
    })
})

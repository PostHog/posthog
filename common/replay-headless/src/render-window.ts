import type { RecordingSegment, RecordingSnapshot } from '@posthog/replay-shared'

/**
 * Keep only the events for the window each segment renders. A single Replayer replays every event,
 * so a background tab open at the same time (for example the marketing site) would rebuild the whole
 * DOM the moment its FullSnapshot plays — painting a page the recorded user never saw and misleading
 * a reader of the frame. The segments already pick one window per time span, so drop events whose
 * window that span does not render.
 *
 * Both inputs are ordered by timestamp, so a single forward pointer walks the segments.
 */
export function eventsForRenderedWindow(
    snapshots: RecordingSnapshot[],
    segments: RecordingSegment[]
): RecordingSnapshot[] {
    if (!segments.length) {
        return [...snapshots]
    }

    let segmentIndex = 0
    const kept: RecordingSnapshot[] = []
    for (const snapshot of snapshots) {
        while (segmentIndex < segments.length - 1 && snapshot.timestamp > segments[segmentIndex].endTimestamp) {
            segmentIndex++
        }
        const renderedWindowId = segments[segmentIndex].windowId
        // A gap with no known window can't decide — keep the event rather than blank the frame.
        if (renderedWindowId === undefined || snapshot.windowId === renderedWindowId) {
            kept.push(snapshot)
        }
    }
    return kept
}

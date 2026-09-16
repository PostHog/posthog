import type { Replayer } from 'posthog-js/rrweb'
import type { eventWithTime } from 'posthog-js/rrweb-types'

import type { RecordingSegment } from '@posthog/replay-shared'

import type { HostBridge } from './host-bridge'

/**
 * Controls playback lifecycle: starts the replayer, skips inactive
 * segments, and stops when the recording finishes or a configured
 * end timestamp is reached.
 */
export class PlaybackController {
    private stopped = false

    constructor(
        private replayer: Replayer,
        private segments: RecordingSegment[],
        private firstTimestamp: number,
        private options: { skipInactivity?: boolean; endOffsetS?: number },
        private bridge: HostBridge
    ) {
        this.replayer.on('finish', () => this.stop())

        if (this.options.endOffsetS != null) {
            const endTs = this.firstTimestamp + this.options.endOffsetS * 1000
            this.replayer.on('event-cast', (event: eventWithTime) => {
                if (event.timestamp >= endTs) {
                    this.replayer.pause()
                    this.stop()
                }
            })
        }
    }

    get isStopped(): boolean {
        return this.stopped
    }

    start(startOffset: number): void {
        this.startPositionLoop()
        this.replayer.play(startOffset)
    }

    stop(): void {
        if (this.stopped) {
            return
        }
        this.stopped = true
        this.bridge.signalEnded()
    }

    /**
     * Poll the current playback position each frame, report every segment the
     * player reaches, and skip the inactive ones. Under puppeteer-capture's
     * virtual time, rAF fires once per beginFrame call, so this is deterministic.
     *
     * The report is what lets the host measure where a segment starts in the
     * captured file. A skip costs at least the frame it is observed on, so a map
     * built from segment durations alone loses a frame per cut.
     */
    private startPositionLoop(): void {
        let current = -1
        const checkPosition = (): void => {
            if (this.stopped) {
                return
            }
            const ts = this.firstTimestamp + this.replayer.getCurrentTime()
            // Adjacent segments share a boundary timestamp, and the later one is what the
            // video shows there, so the end of a range belongs to the segment after it.
            const index = this.segments.findIndex(
                (seg: RecordingSegment) => ts >= seg.startTimestamp && ts < seg.endTimestamp
            )
            if (index !== -1 && index !== current) {
                current = index
                const segment = this.segments[index]
                this.bridge.signalSegmentEntered(index)
                if (this.options.skipInactivity && !segment.isActive) {
                    this.replayer.play(segment.endTimestamp - this.firstTimestamp)
                }
            }
            requestAnimationFrame(checkPosition)
        }
        requestAnimationFrame(checkPosition)
    }
}

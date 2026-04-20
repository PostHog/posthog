import type { RecordingSegment } from '@posthog/replay-shared'
import type { Replayer } from '@posthog/rrweb'
import type { eventWithTime } from '@posthog/rrweb-types'

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
        if (this.options.skipInactivity) {
            this.startInactivitySkipLoop()
        }
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
     * Skip inactive segments by polling the current playback position
     * each frame. Under puppeteer-capture's virtual time, rAF fires
     * once per beginFrame call, so this is deterministic.
     */
    private startInactivitySkipLoop(): void {
        const checkAndSkip = (): void => {
            if (this.stopped) {
                return
            }
            const ts = this.firstTimestamp + this.replayer.getCurrentTime()
            const inactiveSeg = this.segments.find(
                (seg: RecordingSegment) => !seg.isActive && ts >= seg.startTimestamp && ts <= seg.endTimestamp
            )
            if (inactiveSeg) {
                this.replayer.play(inactiveSeg.endTimestamp - this.firstTimestamp)
            }
            requestAnimationFrame(checkAndSkip)
        }
        requestAnimationFrame(checkAndSkip)
    }
}

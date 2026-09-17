import type { Replayer } from 'posthog-js/rrweb'
import type { eventWithTime } from 'posthog-js/rrweb-types'

import type { RecordingSegment } from '@posthog/replay-shared'

import type { HostBridge } from './host-bridge'
import { PLAYER_FRAME_TIMELINE_KEY } from './protocol'

/**
 * Controls playback lifecycle: starts the replayer, skips inactive
 * segments, and stops when the recording finishes or a configured
 * end timestamp is reached.
 */
export class PlaybackController {
    private stopped = false
    private frameSessionMs: number[] = []

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
        this.startFrameLoop()
        this.replayer.play(startOffset)
    }

    getFrameSessionMs(): number[] {
        return this.frameSessionMs
    }

    stop(): void {
        if (this.stopped) {
            return
        }
        this.stopped = true
        this.bridge.publishFrameTimeline(this.frameSessionMs)
        this.bridge.signalEnded()
    }

    /**
     * Record where playback is on every captured frame, and skip inactive segments as they come up.
     * Under puppeteer-capture's virtual time, rAF fires once per beginFrame call, so this is
     * deterministic and each tick is exactly one frame of the rendered video.
     *
     * The sample is taken before the skip: a skip costs the frame it happens on, and recording the
     * position after the jump would hide that frame from the timeline the same way computing video
     * positions from segment durations alone does.
     */
    private startFrameLoop(): void {
        // Published by reference so the host can read it whenever capture ends. Trimmed and timed-out
        // captures tear the page down without the replayer ever finishing, so waiting for stop() to
        // push the timeline would leave exactly the long sessions this exists for without one.
        ;(window as unknown as Record<string, number[]>)[PLAYER_FRAME_TIMELINE_KEY] = this.frameSessionMs
        const onFrame = (): void => {
            if (this.stopped) {
                return
            }
            const current = this.replayer.getCurrentTime()
            this.frameSessionMs.push(Math.round(current))
            if (this.options.skipInactivity) {
                const ts = this.firstTimestamp + current
                const inactiveSeg = this.segments.find(
                    (seg: RecordingSegment) => !seg.isActive && ts >= seg.startTimestamp && ts <= seg.endTimestamp
                )
                if (inactiveSeg) {
                    this.replayer.play(inactiveSeg.endTimestamp - this.firstTimestamp)
                }
            }
            requestAnimationFrame(onFrame)
        }
        requestAnimationFrame(onFrame)
    }
}

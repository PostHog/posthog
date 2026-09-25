import type { Replayer } from 'posthog-js/rrweb'
import type { eventWithTime } from 'posthog-js/rrweb-types'

import type { RecordingSegment } from '@posthog/replay-shared'

import type { HostBridge } from './host-bridge'
import { PLAYER_FRAME_TIMELINE_KEY } from './protocol'

/** One browser tab or window of the recording, replayed on its own timeline. */
export interface PlaybackWindow {
    windowId: number
    replayer: Replayer
    /** Timestamp of the tab's first event, which is the zero of its replayer's clock. */
    firstTimestamp: number
    /** Timestamp of the tab's last event, after which its replayer has nothing left to show. */
    lastTimestamp: number
}

/**
 * Controls playback lifecycle: starts the replayer of the tab on screen, switches windows as the
 * recording's segments move between tabs, skips inactive segments, and stops when the recording finishes
 * or a configured end timestamp is reached.
 *
 * Each tab has its own replayer, as in the web player: rrweb node ids are only unique within a tab,
 * so one replayer fed every tab's events applies one tab's mutations to another tab's DOM.
 */
export class PlaybackController {
    private stopped = false
    private frameSessionMs: number[] = []
    private active: PlaybackWindow
    private windowsById: Map<number, PlaybackWindow>
    private windowChangeListeners: ((tab: PlaybackWindow) => void)[] = []

    constructor(
        windows: PlaybackWindow[],
        private segments: RecordingSegment[],
        private firstTimestamp: number,
        private options: { skipInactivity?: boolean; endOffsetS?: number },
        private bridge: HostBridge
    ) {
        this.windowsById = new Map(windows.map((tab) => [tab.windowId, tab]))
        this.active = windows[0]

        for (const tab of windows) {
            tab.replayer.on('finish', () => this.onFinish(tab))

            if (this.options.endOffsetS != null) {
                const endTs = this.firstTimestamp + this.options.endOffsetS * 1000
                tab.replayer.on('event-cast', (event: eventWithTime) => {
                    if (tab === this.active && event.timestamp >= endTs) {
                        tab.replayer.pause()
                        this.stop()
                    }
                })
            }
        }
    }

    get isStopped(): boolean {
        return this.stopped
    }

    get activeWindow(): PlaybackWindow {
        return this.active
    }

    onWindowChange(listener: (tab: PlaybackWindow) => void): void {
        this.windowChangeListeners.push(listener)
    }

    /** Where playback is, in milliseconds since the recording started. */
    currentSessionMs(): number {
        return this.currentTimestamp() - this.firstTimestamp
    }

    start(startOffset: number): void {
        const ts = this.firstTimestamp + startOffset
        this.activate(this.windowAt(ts) ?? this.active, ts)
        this.startFrameLoop()
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

    private currentTimestamp(): number {
        return this.active.firstTimestamp + Math.max(0, this.active.replayer.getCurrentTime())
    }

    /** The tab that owns the recording at `ts`, preferring an active segment where two meet. */
    private windowAt(ts: number): PlaybackWindow | undefined {
        let fallback: PlaybackWindow | undefined
        for (const seg of this.segments) {
            if (ts < seg.startTimestamp || ts > seg.endTimestamp || seg.windowId == null) {
                continue
            }
            const tab = this.windowsById.get(seg.windowId)
            if (!tab) {
                continue
            }
            if (seg.isActive) {
                return tab
            }
            // A merged inactive run keeps its first window's id even after that window has run out of events.
            if (ts <= tab.lastTimestamp) {
                fallback ??= tab
            }
        }
        return fallback
    }

    private activate(tab: PlaybackWindow, ts: number): void {
        this.active.replayer.pause()
        this.active = tab
        tab.replayer.play(Math.max(0, ts - tab.firstTimestamp))
        for (const listener of this.windowChangeListeners) {
            listener(tab)
        }
    }

    /** A tab runs out of events before the session ends whenever the user moved to another tab. */
    private onFinish(tab: PlaybackWindow): void {
        if (this.stopped || tab !== this.active) {
            return
        }
        const ts = this.currentTimestamp()
        for (const seg of this.segments) {
            const next = seg.windowId != null ? this.windowsById.get(seg.windowId) : undefined
            if (next && next !== tab && seg.endTimestamp > ts) {
                this.activate(next, Math.max(ts, seg.startTimestamp))
                return
            }
        }
        this.stop()
    }

    /**
     * Record where playback is on every captured frame, switch to the tab that owns that moment, and
     * skip inactive segments as they come up. Under puppeteer-capture's virtual time, rAF fires once per
     * beginFrame call, so this is deterministic and each tick is exactly one frame of the rendered video.
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
            const ts = this.currentTimestamp()
            this.frameSessionMs.push(Math.round(ts - this.firstTimestamp))

            let target = ts
            if (this.options.skipInactivity) {
                const inactiveSeg = this.segments.find(
                    (seg: RecordingSegment) => !seg.isActive && ts >= seg.startTimestamp && ts <= seg.endTimestamp
                )
                if (inactiveSeg) {
                    target = inactiveSeg.endTimestamp
                }
            }

            const owner = this.windowAt(target)
            if (owner && owner !== this.active) {
                this.activate(owner, target)
            } else if (target !== ts) {
                this.active.replayer.play(target - this.active.firstTimestamp)
            }
            requestAnimationFrame(onFrame)
        }
        requestAnimationFrame(onFrame)
    }
}

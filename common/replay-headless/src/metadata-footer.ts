import type { RecordingSegment } from '@posthog/replay-shared'

import type { PlaybackController } from './playback-controller'
import { METADATA_FOOTER_HEIGHT_PX } from './protocol'
import type { ReplayerWindow } from './replayer-factory'
import type { WindowLabels } from './window-labels'

/**
 * Renders an overlay footer showing the recording time offset, which window is on screen, that window's
 * page URL, and idle/ended status. Used by the AI summary pipeline to correlate video frames with page
 * context.
 */
export class MetadataFooter {
    private footerEl: HTMLElement | null
    private metaUrlEl: HTMLElement | null
    private metaRectEl: HTMLElement | null
    private metaWindowEl: HTMLElement | null
    private metaStatusEl: HTMLElement | null

    constructor(
        private windows: ReplayerWindow[],
        private segments: RecordingSegment[],
        private firstTimestamp: number,
        private controller: PlaybackController,
        private labels: WindowLabels
    ) {
        this.footerEl = document.getElementById('metadata-footer')
        this.metaUrlEl = document.getElementById('meta-url')
        this.metaRectEl = document.getElementById('meta-rect')
        this.metaWindowEl = document.getElementById('meta-window')
        this.metaStatusEl = document.getElementById('meta-status')

        // The footer's own frame callback runs before the controller's, so without this the frame that switches
        // windows would show the new window's page under the old window's number and URL.
        this.controller.onWindowChange(() => this.update())
    }

    start(): void {
        if (!this.footerEl) {
            return
        }
        this.footerEl.style.display = 'grid'
        this.footerEl.style.height = `${METADATA_FOOTER_HEIGHT_PX}px`

        const onFrame = (): void => {
            this.update()
            if (!this.controller.isStopped) {
                requestAnimationFrame(onFrame)
            }
        }
        requestAnimationFrame(onFrame)
    }

    private update(): void {
        if (!this.metaUrlEl || !this.metaRectEl || !this.metaWindowEl || !this.metaStatusEl) {
            return
        }
        const active = this.controller.activeWindow
        const sessionMs = Math.max(0, this.controller.currentSessionMs())
        this.metaRectEl.textContent = (sessionMs / 1000).toFixed(0)
        this.metaWindowEl.textContent = `${this.labels.numberOf(active.windowId)} of ${this.windows.length}`
        this.metaUrlEl.textContent = this.labels.urlAt(active.windowId, sessionMs)

        if (this.controller.isStopped) {
            this.metaStatusEl.className = 'status-ended'
            this.metaStatusEl.textContent = '[RECORDING ENDED]'
        } else {
            const ts = this.firstTimestamp + sessionMs
            const isIdle = this.segments.some(
                (seg) => !seg.isActive && ts >= seg.startTimestamp && ts <= seg.endTimestamp
            )
            if (isIdle) {
                this.metaStatusEl.className = 'status-idle'
                this.metaStatusEl.textContent = '[IDLE]'
            } else {
                this.metaStatusEl.className = 'status-active'
                this.metaStatusEl.textContent = '[ACTIVE]'
            }
        }
    }
}

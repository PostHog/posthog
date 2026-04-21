import type { RecordingSegment } from '@posthog/replay-shared'
import type { Replayer } from '@posthog/rrweb'
import type { eventWithTime } from '@posthog/rrweb-types'

import type { PlaybackController } from './playback-controller'
import { getMetaHref } from './replayer-factory'

/**
 * Renders an overlay footer showing the current page URL, recording
 * time offset, and idle/ended status. Used by the AI summary pipeline
 * to correlate video frames with page context.
 */
export class MetadataFooter {
    private currentURL = ''
    private footerEl: HTMLElement | null
    private metaUrlEl: HTMLElement | null
    private metaRectEl: HTMLElement | null
    private metaStatusEl: HTMLElement | null

    constructor(
        private replayer: Replayer,
        private segments: RecordingSegment[],
        private firstTimestamp: number,
        private controller: PlaybackController,
        initialURL: string
    ) {
        this.currentURL = initialURL
        this.footerEl = document.getElementById('metadata-footer')
        this.metaUrlEl = document.getElementById('meta-url')
        this.metaRectEl = document.getElementById('meta-rect')
        this.metaStatusEl = document.getElementById('meta-status')

        this.replayer.on('event-cast', (event: eventWithTime) => {
            const href = getMetaHref(event)
            if (href) {
                this.currentURL = href
            }
        })
    }

    start(): void {
        if (!this.footerEl) {
            return
        }
        this.footerEl.style.display = 'flex'

        const onFrame = (): void => {
            this.update()
            if (!this.controller.isStopped) {
                requestAnimationFrame(onFrame)
            }
        }
        requestAnimationFrame(onFrame)
    }

    private update(): void {
        if (!this.metaUrlEl || !this.metaRectEl || !this.metaStatusEl) {
            return
        }
        this.metaUrlEl.textContent = this.currentURL
        this.metaRectEl.textContent = (Math.max(0, this.replayer.getCurrentTime()) / 1000).toFixed(0)

        if (this.controller.isStopped) {
            this.metaStatusEl.className = 'status-ended'
            this.metaStatusEl.textContent = '[RECORDING ENDED]'
        } else {
            const ts = this.firstTimestamp + Math.max(0, this.replayer.getCurrentTime())
            const isIdle = this.segments.some(
                (seg) => !seg.isActive && ts >= seg.startTimestamp && ts <= seg.endTimestamp
            )
            if (isIdle) {
                this.metaStatusEl.className = 'status-idle'
                this.metaStatusEl.textContent = '[IDLE]'
            } else {
                this.metaStatusEl.className = ''
                this.metaStatusEl.textContent = ''
            }
        }
    }
}

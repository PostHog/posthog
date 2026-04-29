import type { Replayer } from '@posthog/rrweb'

/**
 * Scales the recording's native resolution to fit within the browser
 * viewport, centering the content and accounting for an optional
 * footer bar.
 */
export class ViewportScaler {
    constructor(
        private contentEl: HTMLElement,
        private footerHeight: number
    ) {}

    apply(recWidth: number, recHeight: number): void {
        const availW = window.innerWidth
        const availH = window.innerHeight - this.footerHeight
        if (recWidth <= 0 || recHeight <= 0 || availW <= 0 || availH <= 0) {
            return
        }
        const scale = Math.min(availW / recWidth, availH / recHeight)
        const scaledW = recWidth * scale
        const scaledH = recHeight * scale
        const offsetX = (availW - scaledW) / 2
        const offsetY = (availH - scaledH) / 2
        // Clip the content element to the recording's native size, then
        // scale it down and center within the available space.
        this.contentEl.style.width = `${recWidth}px`
        this.contentEl.style.height = `${recHeight}px`
        this.contentEl.style.overflow = 'hidden'
        this.contentEl.style.transformOrigin = 'top left'
        this.contentEl.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`
    }

    attachToReplayer(replayer: Replayer): void {
        const iframeWidth = Number.parseFloat(replayer.iframe.width)
        const iframeHeight = Number.parseFloat(replayer.iframe.height)
        if (iframeWidth > 0 && iframeHeight > 0) {
            this.apply(iframeWidth, iframeHeight)
        }

        replayer.on('resize', (dimension: { width: number; height: number }) => {
            this.apply(dimension.width, dimension.height)
        })
    }
}

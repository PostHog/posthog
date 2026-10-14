import { footerUrl } from './footer-url'
import type { PageUrls } from './page-urls'
import type { PlaybackController } from './playback-controller'
import { PLAYER_NAVIGATION_KEY, type NavigationSample } from './protocol'

/** Bounds what one render writes into its asset. */
export const MAX_NAVIGATION_SAMPLES = 2000

/** Reads the state the footer draws, so it lists what the video shows rather than what analytics events claim. */
export class NavigationTimeline {
    private samples: NavigationSample[] = []

    constructor(
        private controller: PlaybackController,
        private pageUrls: PageUrls,
        private windowUuidById: Map<number, string>
    ) {}

    start(): void {
        // Published by reference so a capture torn down before playback ends still has it.
        ;(window as unknown as Record<string, NavigationSample[]>)[PLAYER_NAVIGATION_KEY] = this.samples
        this.controller.onFrame((sample) => this.record(sample))
    }

    private record(sample: number): void {
        if (this.samples.length >= MAX_NAVIGATION_SAMPLES) {
            return
        }
        const tab = this.controller.activeWindow
        const windowUuid = this.windowUuidById.get(tab.windowId)
        const url = footerUrl(this.pageUrls.urlOf(tab.windowId))
        if (!windowUuid || !url) {
            return
        }
        const last = this.samples[this.samples.length - 1]
        if (last && last.window_id === windowUuid && last.url === url) {
            return
        }
        this.samples.push({
            sample,
            session_ms: Math.round(this.controller.currentSessionMs()),
            window_id: windowUuid,
            url,
        })
    }
}

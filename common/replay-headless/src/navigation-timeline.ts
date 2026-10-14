import type { PlaybackController } from './playback-controller'
import { PLAYER_NAVIGATION_KEY, type NavigationSample } from './protocol'
import type { WindowLabels } from './window-labels'

/** Bounds what one render writes into its asset. */
export const MAX_NAVIGATION_SAMPLES = 500
const MAX_URL_LENGTH = 500

/** Reads the state the footer draws, so it lists what the video shows rather than what analytics events claim. */
export class NavigationTimeline {
    private samples: NavigationSample[] = []

    constructor(
        private controller: PlaybackController,
        private labels: WindowLabels,
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
        const sessionMs = Math.round(this.controller.currentSessionMs())
        const windowNumber = this.labels.numberOf(tab.windowId)
        const url = this.labels.urlAt(tab.windowId, sessionMs).slice(0, MAX_URL_LENGTH)
        if (!windowUuid || windowNumber === undefined || !url) {
            return
        }
        const last = this.samples[this.samples.length - 1]
        if (last && last.window_id === windowUuid && last.url === url) {
            return
        }
        this.samples.push({
            sample,
            session_ms: sessionMs,
            window_id: windowUuid,
            window_number: windowNumber,
            url,
        })
    }
}

import { footerUrl } from './footer-url'
import type { ReplayerWindow } from './replayer-factory'

/** What the footer labels each window with, shared so the navigation timeline names tabs the way frames show them. */
export class WindowLabels {
    private urlsByWindow = new Map<number, { timestamp: number; url: string }[]>()
    private numberByWindow = new Map<number, number>()

    constructor(
        windows: ReplayerWindow[],
        private firstTimestamp: number
    ) {
        windows.forEach((tab, index) => this.numberByWindow.set(tab.windowId, index + 1))
        for (const tab of windows) {
            this.urlsByWindow.set(
                tab.windowId,
                tab.hrefChanges.map((change) => ({ timestamp: change.timestamp, url: footerUrl(change.href) }))
            )
        }
    }

    /** Read from the recorded history rather than the replayer's casts, which skip Custom events while seeking. */
    urlAt(windowId: number, sessionMs: number): string {
        const urls = this.urlsByWindow.get(windowId) ?? []
        const ts = this.firstTimestamp + sessionMs
        let low = 0
        let high = urls.length - 1
        let found = 0
        while (low <= high) {
            const mid = (low + high) >> 1
            if (urls[mid].timestamp <= ts) {
                found = mid
                low = mid + 1
            } else {
                high = mid - 1
            }
        }
        return urls[found]?.url ?? ''
    }

    numberOf(windowId: number): number | undefined {
        return this.numberByWindow.get(windowId)
    }
}

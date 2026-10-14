import type { eventWithTime } from 'posthog-js/rrweb-types'

import { getHrefFromSnapshot } from '@posthog/replay-shared'

import { footerUrl } from './footer-url'
import type { ReplayerWindow } from './replayer-factory'

/** What the footer labels each window with, shared so the navigation timeline names tabs the way frames show them. */
export class WindowLabels {
    private urlByWindow = new Map<number, string>()
    private numberByWindow = new Map<number, number>()

    constructor(windows: ReplayerWindow[]) {
        windows.forEach((tab, index) => this.numberByWindow.set(tab.windowId, index + 1))
        for (const tab of windows) {
            this.urlByWindow.set(tab.windowId, footerUrl(tab.initialURL))
            // Custom events carry the URL of in-page navigations, which record no Meta event.
            tab.replayer.on('event-cast', (event: eventWithTime) => {
                const href = getHrefFromSnapshot(event)
                if (href) {
                    this.urlByWindow.set(tab.windowId, footerUrl(href))
                }
            })
        }
    }

    urlOf(windowId: number): string {
        return this.urlByWindow.get(windowId) ?? ''
    }

    numberOf(windowId: number): number | undefined {
        return this.numberByWindow.get(windowId)
    }
}

import type { eventWithTime } from 'posthog-js/rrweb-types'

import { getHrefFromSnapshot } from '@posthog/replay-shared'

import type { ReplayerWindow } from './replayer-factory'

export class PageUrls {
    private urlByWindow = new Map<number, string>()

    constructor(windows: ReplayerWindow[]) {
        for (const tab of windows) {
            this.urlByWindow.set(tab.windowId, tab.initialURL)
            // Custom events carry the URL of in-page navigations, which record no Meta event.
            tab.replayer.on('event-cast', (event: eventWithTime) => {
                const href = getHrefFromSnapshot(event)
                if (href) {
                    this.urlByWindow.set(tab.windowId, href)
                }
            })
        }
    }

    urlOf(windowId: number): string {
        return this.urlByWindow.get(windowId) ?? ''
    }
}

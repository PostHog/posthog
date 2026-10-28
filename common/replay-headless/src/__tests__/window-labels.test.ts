import type { ReplayerWindow } from '../replayer-factory'
import { WindowLabels } from '../window-labels'

describe('WindowLabels', () => {
    const windows = [
        {
            windowId: 7,
            hrefChanges: [
                { timestamp: 1000, href: 'https://ex.com/flags?tab=overview' },
                { timestamp: 5000, href: 'https://ex.com/billing' },
            ],
        },
    ] as unknown as ReplayerWindow[]

    it.each([
        [0, 'https://ex.com/flags'],
        // A seek that lands past the in-page navigation shows the later page, though the replayer cast no event for it.
        [9000, 'https://ex.com/billing'],
    ])('reads the page shown %i ms into the recording from the recorded history', (sessionMs, url) => {
        expect(new WindowLabels(windows, 1000).urlAt(7, sessionMs)).toBe(url)
    })
})

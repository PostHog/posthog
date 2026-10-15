import { urlHistoryExpiresAtMs } from './url-history-expiry'

describe('urlHistoryExpiresAtMs', () => {
    const NOW_MS = Date.parse('2026-10-15T12:00:00Z')
    const TTL_SECONDS = 30 * 24 * 60 * 60

    it.each([
        // A month-scoped image is write-once for its month, so it is not fetched again before the partition ends.
        ['a v3 reference', 'imageurl:v3:7:2026-10:aaaaaaaaaaaaaaaaaaaaaa', Date.parse('2026-11-09T00:00:00Z')],
        // The v4 lane fetches a reference only inside its 7-day raw window, so its entry ends at day + 8.
        ['a v4 reference', 'imageurl:v4:7:2026-10-15:aaaaaaaaaaaaaaaaaaaaaa', Date.parse('2026-10-24T00:00:00Z')],
        ['a global reference', 'imageurl:aaaaaaaaaaaaaaaaaaaaaa', NOW_MS + TTL_SECONDS * 1000],
    ])('expires the history of %s', (_name, ref, expected) => {
        expect(urlHistoryExpiresAtMs(ref, NOW_MS, TTL_SECONDS)).toBe(expected)
    })
})

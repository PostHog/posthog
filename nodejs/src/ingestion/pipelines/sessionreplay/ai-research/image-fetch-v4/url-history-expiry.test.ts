import { urlHistoryExpiresAtMs, urlHistoryStorageExpiresAtMs } from './url-history-expiry'

describe('url history expiry', () => {
    const NOW_MS = Date.parse('2026-10-15T12:00:00Z')
    const TTL_SECONDS = 30 * 24 * 60 * 60

    it('fetches a v4 reference again after the TTL', () => {
        expect(urlHistoryExpiresAtMs(NOW_MS, TTL_SECONDS)).toBe(NOW_MS + TTL_SECONDS * 1000)
    })

    it.each([
        ['during its month', '2026-10', NOW_MS, '2026-11-09T00:00:00Z'],
        ['in December', '2026-12', NOW_MS, '2027-01-09T00:00:00Z'],
        ['after its month ends', '2026-10', Date.parse('2026-11-12T06:00:00Z'), '2026-11-20T06:00:00Z'],
    ])(
        'keeps the entry of a v4 reference written %s until 8 days after the later of its month end and the write',
        (_when, month, writtenAtMs, expected) => {
            const nextFetchAtMs = urlHistoryExpiresAtMs(writtenAtMs, TTL_SECONDS)
            expect(
                urlHistoryStorageExpiresAtMs(
                    `imageurl:v4:7:${month}:aaaaaaaaaaaaaaaaaaaaaa`,
                    nextFetchAtMs,
                    writtenAtMs
                )
            ).toBe(Date.parse(expected))
        }
    )
})

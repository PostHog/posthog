import { accessTokenExpired, nowSecs } from './expiry'

describe('accessTokenExpired', () => {
    const now = nowSecs()

    it.each<[string, string, Record<string, any>, boolean]>([
        ['no timing fields never refreshes', 'hubspot', {}, false],
        ['only expires_in never refreshes', 'hubspot', { expires_in: 3600 }, false],
        ['only refreshed_at never refreshes', 'hubspot', { refreshed_at: now }, false],
        ['fresh, before half-life', 'hubspot', { expires_in: 3600, refreshed_at: now - 100 }, false],
        ['stale, past half-life', 'hubspot', { expires_in: 3600, refreshed_at: now - 3000 }, true],
        ['salesforce defaults expires_in=3600 -> stale', 'salesforce', { refreshed_at: now - 3000 }, true],
        ['stripe defaults expires_in=3600 -> stale', 'stripe', { refreshed_at: now - 3000 }, true],
        ['hubspot has no default so never refreshes', 'hubspot', { refreshed_at: now - 3000 }, false],
        ['non-positive expires_in never refreshes', 'hubspot', { expires_in: 0, refreshed_at: now - 3000 }, false],
    ])('%s', (_name, kind, config, expected) => {
        expect(accessTokenExpired(kind, config)).toBe(expected)
    })
})

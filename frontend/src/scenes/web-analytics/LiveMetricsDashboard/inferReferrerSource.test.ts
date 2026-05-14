import {
    addReferrerEntry,
    buildTrafficSourceExpressions,
    collapseToRawReferrerEntries,
    resolvedTrafficSourceFromHogQL,
    resolveTrafficSource,
    subtractReferrerEntry,
} from './inferReferrerSource'
import { DIRECT_REFERRER, type ResolvedTrafficSource, type TrafficSourceKind } from './LiveWebAnalyticsMetricsTypes'

const source = (source: string, kind: ResolvedTrafficSource['kind']): ResolvedTrafficSource => ({ source, kind })

describe('resolveTrafficSource', () => {
    it('uses utm_source before referrer, click ID, and UA signals', () => {
        expect(
            resolveTrafficSource({
                $utm_source: 'instagram',
                $referring_domain: 'facebook.com',
                gclid: 'abc',
                $raw_user_agent: 'Mozilla/5.0 Reddit/2024.10.0',
            })
        ).toEqual(source('instagram', 'utm'))
    })

    it('uses the browser referrer before click ID and UA signals', () => {
        expect(
            resolveTrafficSource({
                $referring_domain: 'reddit.com',
                fbclid: 'abc',
                $raw_user_agent: 'Mozilla/5.0 Instagram 305.0.0.45.109',
            })
        ).toEqual(source('reddit.com', 'referrer'))
    })

    it.each<{ property: string; value: string; expected: string }>([
        { property: 'fbclid', value: 'IwAR0', expected: 'facebook.com' },
        { property: 'igshid', value: 'MzRlODBiNWFlZA==', expected: 'instagram.com' },
        { property: 'ttclid', value: 'E.C.P.AAB', expected: 'tiktok.com' },
        { property: 'twclid', value: '2-abc', expected: 'x.com' },
        { property: 'li_fat_id', value: 'a1b2c3', expected: 'linkedin.com' },
        { property: 'msclkid', value: 'xyz', expected: 'bing.com' },
        { property: 'gclid', value: 'Cj0KCQ', expected: 'google.com' },
    ])('maps $property to $expected', ({ property, value, expected }) => {
        expect(resolveTrafficSource({ [property]: value })).toEqual(source(expected, 'click_id'))
    })

    it('prefers the first matching click ID rule over later rules and UA signals', () => {
        expect(
            resolveTrafficSource({
                fbclid: 'a',
                gclid: 'b',
                $raw_user_agent: 'Mozilla/5.0 Instagram 305.0.0.45.109',
            })
        ).toEqual(source('google.com', 'click_id'))
    })

    it.each<{ ua: string; expected: string }>([
        {
            ua: 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 [FBAN/FBIOS;FBAV/444.0]',
            expected: 'facebook.com',
        },
        {
            ua: 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 [FBAN/EMA;FBLC/en_US]',
            expected: 'facebook.com',
        },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 [FBAV/444.0]', expected: 'facebook.com' },
        { ua: 'Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 [FBAN/EMA]', expected: 'facebook.com' },
        {
            ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Mobile/15E148 Instagram 305.0.0.45.109',
            expected: 'instagram.com',
        },
        {
            ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 musical_ly_29.5.0 JsSdk/2.0 BytedanceWebview/d8a21c5',
            expected: 'tiktok.com',
        },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 BytedanceWebview/d8a21c5', expected: 'tiktok.com' },
        { ua: 'Mozilla/5.0 (Linux; Android 13) musical_ly_29.5.0', expected: 'tiktok.com' },
        { ua: 'Mozilla/5.0 (Linux; Android 13) TikTok 29.5.0', expected: 'tiktok.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 LinkedInApp/9.27.1234', expected: 'linkedin.com' },
        { ua: 'Mozilla/5.0 (Android 13) com.linkedin.android LinkedInApp/4.1.999', expected: 'linkedin.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 [Pinterest/iOS]', expected: 'pinterest.com' },
        { ua: 'Mozilla/5.0 (Android) Pinterest/Android 11.40.0', expected: 'pinterest.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Snapchat/12.45.0.30', expected: 'snapchat.com' },
        { ua: 'Mozilla/5.0 (Linux; Android 13) Snapchat/12.45.0.30', expected: 'snapchat.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Reddit/2024.10.0', expected: 'reddit.com' },
        { ua: 'Mozilla/5.0 (Linux; Android 13) Reddit/2024.41.1', expected: 'reddit.com' },
    ])('infers $expected from in-app UA', ({ ua, expected }) => {
        expect(resolveTrafficSource({ $raw_user_agent: ua })).toEqual(source(expected, 'user_agent'))
    })

    it.each<{ ua: string }>([
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Safari/604.1' },
        { ua: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0' },
        { ua: 'Mozilla/5.0 (Linux; Android 13) Chrome/120.0.0.0 Mobile' },
        { ua: 'instagram lowercase should not match' },
        { ua: 'no social signals here' },
        { ua: '' },
    ])('returns direct for browser UA without app signals "$ua"', ({ ua }) => {
        expect(resolveTrafficSource({ $raw_user_agent: ua })).toEqual(source(DIRECT_REFERRER, 'direct'))
    })

    it.each<{ value: unknown }>([
        { value: '' },
        { value: '   ' },
        { value: '\t' },
        { value: '\n' },
        { value: '\r\n' },
        { value: null },
        { value: undefined },
        { value: DIRECT_REFERRER },
        { value: ` ${DIRECT_REFERRER} ` },
        { value: `\t${DIRECT_REFERRER}\n` },
        { value: 0 },
        { value: 42 },
        { value: false },
        { value: true },
    ])('falls through blank, non-string, or direct referrer value "$value"', ({ value }) => {
        expect(resolveTrafficSource({ $referring_domain: value, fbclid: 'abc' })).toEqual(
            source('facebook.com', 'click_id')
        )
    })

    it.each<{ value: unknown }>([
        { value: '' },
        { value: '   ' },
        { value: '\t\n' },
        { value: null },
        { value: undefined },
        { value: 0 },
        { value: 42 },
        { value: false },
        { value: true },
    ])('falls through blank or non-string click ID value "$value"', ({ value }) => {
        expect(resolveTrafficSource({ gclid: value })).toEqual(source(DIRECT_REFERRER, 'direct'))
    })

    it.each<{ property: string; value: string; expected: string }>([
        { property: 'gclid', value: '  Cj0KCQ  ', expected: 'google.com' },
        { property: 'fbclid', value: '\tIwAR0\n', expected: 'facebook.com' },
        { property: 'ttclid', value: '   E.C.P.AAB', expected: 'tiktok.com' },
    ])('resolves whitespace-padded click ID $property to $expected', ({ property, value, expected }) => {
        expect(resolveTrafficSource({ [property]: value })).toEqual(source(expected, 'click_id'))
    })

    it.each<{ value: unknown }>([
        { value: '' },
        { value: '   ' },
        { value: '\t\n' },
        { value: null },
        { value: undefined },
        { value: 0 },
        { value: false },
    ])('falls through blank or non-string utm_source value "$value"', ({ value }) => {
        expect(resolveTrafficSource({ $utm_source: value })).toEqual(source(DIRECT_REFERRER, 'direct'))
    })

    it('trims UTM and referrer source values', () => {
        expect(resolveTrafficSource({ $utm_source: ' instagram ' })).toEqual(source('instagram', 'utm'))
        expect(resolveTrafficSource({ $referring_domain: ' reddit.com ' })).toEqual(source('reddit.com', 'referrer'))
    })

    it('returns direct when no signal is present', () => {
        expect(resolveTrafficSource(undefined)).toEqual(source(DIRECT_REFERRER, 'direct'))
    })

    it('returns direct when properties is an empty object', () => {
        expect(resolveTrafficSource({})).toEqual(source(DIRECT_REFERRER, 'direct'))
    })

    it.each<{ kind: TrafficSourceKind }>([
        { kind: 'utm' },
        { kind: 'referrer' },
        { kind: 'click_id' },
        { kind: 'user_agent' },
        { kind: 'direct' },
    ])('resolvedTrafficSourceFromHogQL round-trips kind $kind', ({ kind }) => {
        expect(resolvedTrafficSourceFromHogQL('foo.com', kind)).toEqual({ source: 'foo.com', kind })
    })

    it('defaults resolvedTrafficSourceFromHogQL to DIRECT_REFERRER when source is empty', () => {
        expect(resolvedTrafficSourceFromHogQL('', 'direct')).toEqual(source(DIRECT_REFERRER, 'direct'))
    })

    describe('source count helpers', () => {
        it('adds, subtracts, and collapses non-referrer sources to direct', () => {
            const entries = new Map()

            addReferrerEntry(entries, source('facebook.com', 'referrer'), 3)
            addReferrerEntry(entries, source('facebook.com', 'click_id'), 2)
            addReferrerEntry(entries, source('instagram', 'utm'), 1)
            subtractReferrerEntry(entries, source('facebook.com', 'click_id'), 1)

            expect(collapseToRawReferrerEntries(entries)).toEqual(
                new Map([
                    ['facebook.com', 3],
                    [DIRECT_REFERRER, 2],
                ])
            )
        })

        it.each<{ count: number }>([{ count: 0 }, { count: -1 }, { count: -100 }])(
            'addReferrerEntry ignores non-positive count $count',
            ({ count }) => {
                const entries = new Map()
                addReferrerEntry(entries, source('facebook.com', 'referrer'), count)
                expect(entries.size).toBe(0)
            }
        )

        it('addReferrerEntry accumulates counts for the same source and kind', () => {
            const entries = new Map()
            addReferrerEntry(entries, source('reddit.com', 'referrer'), 2)
            addReferrerEntry(entries, source('reddit.com', 'referrer'), 5)

            expect(collapseToRawReferrerEntries(entries)).toEqual(new Map([['reddit.com', 7]]))
        })

        it('addReferrerEntry keeps entries with the same source but different kinds separate', () => {
            const entries = new Map()
            addReferrerEntry(entries, source('facebook.com', 'referrer'), 4)
            addReferrerEntry(entries, source('facebook.com', 'click_id'), 6)

            expect(entries.size).toBe(2)
            expect(collapseToRawReferrerEntries(entries)).toEqual(
                new Map([
                    ['facebook.com', 4],
                    [DIRECT_REFERRER, 6],
                ])
            )
        })

        it('subtractReferrerEntry is a no-op when the entry is missing', () => {
            const entries = new Map()
            subtractReferrerEntry(entries, source('facebook.com', 'referrer'), 5)
            expect(entries.size).toBe(0)
        })

        it.each<{ subtract: number }>([{ subtract: 3 }, { subtract: 5 }, { subtract: 100 }])(
            'subtractReferrerEntry removes the entry when subtraction reaches or exceeds the count ($subtract)',
            ({ subtract }) => {
                const entries = new Map()
                addReferrerEntry(entries, source('reddit.com', 'referrer'), 3)
                subtractReferrerEntry(entries, source('reddit.com', 'referrer'), subtract)
                expect(entries.size).toBe(0)
            }
        )

        it('subtractReferrerEntry decrements the count when subtraction is partial', () => {
            const entries = new Map()
            addReferrerEntry(entries, source('reddit.com', 'referrer'), 10)
            subtractReferrerEntry(entries, source('reddit.com', 'referrer'), 3)

            expect(collapseToRawReferrerEntries(entries)).toEqual(new Map([['reddit.com', 7]]))
        })

        it('collapseToRawReferrerEntries returns an empty map for an empty input', () => {
            expect(collapseToRawReferrerEntries(new Map())).toEqual(new Map())
        })

        it('collapseToRawReferrerEntries merges different non-referrer kinds into direct', () => {
            const entries = new Map()
            addReferrerEntry(entries, source('google.com', 'click_id'), 4)
            addReferrerEntry(entries, source('instagram', 'utm'), 2)
            addReferrerEntry(entries, source('tiktok.com', 'user_agent'), 1)

            expect(collapseToRawReferrerEntries(entries)).toEqual(new Map([[DIRECT_REFERRER, 7]]))
        })

        it('builds HogQL guards and emits source kind metadata', () => {
            const { sourceExpr, kindExpr } = buildTrafficSourceExpressions(
                'properties.$utm_source',
                'properties.$referring_domain',
                'properties.$raw_user_agent'
            )

            expect(sourceExpr).toContain("trim(toString(ifNull(properties.$utm_source, ''))) != ''")
            expect(sourceExpr).toContain("trim(toString(ifNull(properties.$referring_domain, ''))) != ''")
            expect(sourceExpr).toContain("trim(toString(ifNull(properties.gclid, ''))) != ''")
            expect(sourceExpr).toContain(
                "position(trim(toString(ifNull(properties.$raw_user_agent, ''))), 'Instagram ')"
            )
            expect(kindExpr).toContain("'utm'")
            expect(kindExpr).toContain("'referrer'")
            expect(kindExpr).toContain("'click_id'")
            expect(kindExpr).toContain("'user_agent'")
        })

        it('emits the same branch predicates for source and kind expressions', () => {
            const { sourceExpr, kindExpr } = buildTrafficSourceExpressions(
                'properties.$utm_source',
                'properties.$referring_domain',
                'properties.$raw_user_agent'
            )

            const countOccurrences = (haystack: string, needle: string): number => haystack.split(needle).length - 1

            for (const predicate of [
                "trim(toString(ifNull(properties.gclid, ''))) != ''",
                "trim(toString(ifNull(properties.fbclid, ''))) != ''",
                "position(trim(toString(ifNull(properties.$raw_user_agent, ''))), 'Instagram ')",
                "position(trim(toString(ifNull(properties.$raw_user_agent, ''))), 'Reddit/')",
            ]) {
                expect(countOccurrences(sourceExpr, predicate)).toBe(countOccurrences(kindExpr, predicate))
                expect(countOccurrences(sourceExpr, predicate)).toBeGreaterThan(0)
            }
        })
    })
})

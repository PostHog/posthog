import {
    addReferrerEntry,
    buildTrafficSourceHogQL,
    buildTrafficSourceKindHogQL,
    collapseToRawReferrerEntries,
    resolveTrafficSource,
    subtractReferrerEntry,
} from './inferReferrerSource'
import { DIRECT_REFERRER, type ResolvedTrafficSource } from './LiveWebAnalyticsMetricsTypes'

const source = (
    source: string,
    kind: ResolvedTrafficSource['kind'],
    confidence: ResolvedTrafficSource['confidence']
): ResolvedTrafficSource => ({ source, kind, confidence })

describe('resolveTrafficSource', () => {
    it('uses utm_source before referrer, click ID, and UA signals', () => {
        expect(
            resolveTrafficSource({
                $utm_source: 'instagram',
                $referring_domain: 'facebook.com',
                gclid: 'abc',
                $raw_user_agent: 'Mozilla/5.0 Reddit/2024.10.0',
            })
        ).toEqual(source('instagram', 'utm', 'high'))
    })

    it('uses the browser referrer before click ID and UA signals', () => {
        expect(
            resolveTrafficSource({
                $referring_domain: 'reddit.com',
                fbclid: 'abc',
                $raw_user_agent: 'Mozilla/5.0 Instagram 305.0.0.45.109',
            })
        ).toEqual(source('reddit.com', 'referrer', 'high'))
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
        expect(resolveTrafficSource({ [property]: value })).toEqual(source(expected, 'click_id', 'medium'))
    })

    it('uses the first matching click ID before UA signals', () => {
        expect(
            resolveTrafficSource({
                fbclid: 'a',
                gclid: 'b',
                $raw_user_agent: 'Mozilla/5.0 Instagram 305.0.0.45.109',
            })
        ).toEqual(source('google.com', 'click_id', 'medium'))
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
        {
            ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Mobile/15E148 Instagram 305.0.0.45.109',
            expected: 'instagram.com',
        },
        {
            ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 musical_ly_29.5.0 JsSdk/2.0 BytedanceWebview/d8a21c5',
            expected: 'tiktok.com',
        },
        { ua: 'Mozilla/5.0 (Linux; Android 13) TikTok 29.5.0', expected: 'tiktok.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 LinkedInApp/9.27.1234', expected: 'linkedin.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 [Pinterest/iOS]', expected: 'pinterest.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Snapchat/12.45.0.30', expected: 'snapchat.com' },
        { ua: 'Mozilla/5.0 (iPhone) AppleWebKit/605.1.15 Reddit/2024.10.0', expected: 'reddit.com' },
    ])('infers $expected from in-app UA', ({ ua, expected }) => {
        expect(resolveTrafficSource({ $raw_user_agent: ua })).toEqual(source(expected, 'user_agent', 'low'))
    })

    it.each([{ value: '' }, { value: '   ' }, { value: null }, { value: undefined }, { value: DIRECT_REFERRER }])(
        'falls through blank or direct referrer value "$value"',
        ({ value }) => {
            expect(resolveTrafficSource({ $referring_domain: value, fbclid: 'abc' })).toEqual(
                source('facebook.com', 'click_id', 'medium')
            )
        }
    )

    it('returns direct when no signal is present', () => {
        expect(resolveTrafficSource(undefined)).toEqual(source(DIRECT_REFERRER, 'direct', 'high'))
    })

    describe('source count helpers', () => {
        it('adds, subtracts, and collapses non-referrer sources to direct', () => {
            const entries = new Map()

            addReferrerEntry(entries, source('facebook.com', 'referrer', 'high'), 3)
            addReferrerEntry(entries, source('facebook.com', 'click_id', 'medium'), 2)
            addReferrerEntry(entries, source('instagram', 'utm', 'high'), 1)
            subtractReferrerEntry(entries, source('facebook.com', 'click_id', 'medium'), 1)

            expect(collapseToRawReferrerEntries(entries)).toEqual(
                new Map([
                    ['facebook.com', 3],
                    [DIRECT_REFERRER, 2],
                ])
            )
        })

        it('builds HogQL guards and emits source kind metadata', () => {
            const sourceHogql = buildTrafficSourceHogQL(
                'properties.$utm_source',
                'properties.$referring_domain',
                'properties.$raw_user_agent'
            )
            const kindHogql = buildTrafficSourceKindHogQL(
                'properties.$utm_source',
                'properties.$referring_domain',
                'properties.$raw_user_agent'
            )

            expect(sourceHogql).toContain('properties.$utm_source IS NOT NULL')
            expect(sourceHogql).toContain('properties.$referring_domain IS NOT NULL')
            expect(sourceHogql).toContain('properties.gclid IS NOT NULL')
            expect(sourceHogql).toContain('properties.$raw_user_agent IS NOT NULL')
            expect(kindHogql).toContain("'utm'")
            expect(kindHogql).toContain("'referrer'")
            expect(kindHogql).toContain("'click_id'")
            expect(kindHogql).toContain("'user_agent'")
        })
    })
})

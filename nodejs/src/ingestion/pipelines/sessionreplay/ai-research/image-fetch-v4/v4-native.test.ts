import {
    isPublicHost,
    parseV4UrlRef,
    politenessKey,
    publicFontRefOf,
    tryCanonicalizeUrl,
} from '@posthog/ai-research-v4-native'

import vector from '~/ingestion/pipelines/sessionreplay/ai-research/v4-keys/encryption-vector-v4.json'
import { parseImageRef } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/content-ref'

/**
 * The crate owns the rule and tests it. This file tests only that the fetch lane reaches that
 * function across the FFI boundary, so every case here asserts behaviour the crate already had.
 */
describe('the v4 url policy addon', () => {
    it('returns the canonical forms of a url and refuses a private host', () => {
        // Values from the url_policy tests in replay-core-v4: the dedup form drops the volatile
        // parameters, and the fetch form keeps every byte.
        const raw = 'https://cdn.example.com/a.png?w=200&%63b=first&CB=second&no%63ache=third&RND=fourth'
        expect(tryCanonicalizeUrl(raw)).toEqual({
            ok: true,
            url: {
                fetch: raw,
                dedup: 'https://cdn.example.com/a.png?w=200',
                host: 'cdn.example.com',
                domain: 'example.com',
            },
        })
        expect(tryCanonicalizeUrl('https://169.254.169.254/latest/meta-data/iam/security-credentials/')).toEqual({
            ok: false,
            decline: 'non_public_host',
            unwanted: false,
        })
        expect(isPublicHost('169.254.169.254')).toBe(false)
    })

    describe('politenessKey', () => {
        it.each([['d111.cloudfront.net'], ['bucket.s3.amazonaws.com'], ['user.github.io'], ['myapp.vercel.app']])(
            'keeps %s as its own operator',
            (host) => {
                // Each provider sits in the private section of the public suffix list. A list read
                // without that section folds every tenant of one provider into a single rate budget.
                expect(politenessKey(host)).toBe(host)
            }
        )

        it.each([
            ['img1.cdn.example.com', 'example.com'],
            ['a.b.example.co.uk', 'example.co.uk'],
        ])('folds %s onto %s', (host, expected) => {
            expect(politenessKey(host)).toBe(expected)
        })

        it.each([['203.0.113.4'], ['::1']])('returns the address %s unchanged', (host) => {
            expect(politenessKey(host)).toBe(host)
        })
    })

    describe('parseV4UrlRef', () => {
        const hash = 'a'.repeat(22)

        it.each([
            ['imageurl', 'image'],
            ['fonturl', 'font'],
        ])('parses a month-scoped v4 %s ref that no v2 or v3 reader takes', (prefix, asset) => {
            const ref = `${prefix}:v4:7:2026-10:${hash}`
            expect(parseV4UrlRef(ref)).toEqual({ scope: 'team', asset, teamId: 7, keyMonth: '2026-10', hash })
            expect(parseImageRef(ref)).toBeNull()
        })

        it('names a public font file by the same reference as the recorder, and no other URL', () => {
            const ref = publicFontRefOf(vector.publicFontUrl.url)
            expect(ref).toBe(vector.publicFontUrl.ref)
            expect(parseV4UrlRef(ref!)).toEqual({ scope: 'public', asset: 'font', hash: ref!.split(':').pop() })
            expect(parseImageRef(ref!)).toBeNull()
            expect(vector.publicFontUrl.teamUrls.map(publicFontRefOf)).toEqual(
                vector.publicFontUrl.teamUrls.map(() => null)
            )
        })

        it.each([
            ['a content ref', `image:v4:7:2026-10:${hash}`],
            ['a team id that a number cannot hold exactly', `imageurl:v4:9007199254740993:2026-10:${hash}`],
            ['a bundled font marker, which names no URL', 'fonturl:v4:bundled:open-sans'],
            ['a public image ref, which the recorder never writes', `imageurl:v4:public:${hash}`],
        ])('refuses %s', (_name, ref) => {
            expect(parseV4UrlRef(ref)).toBeNull()
        })
    })

    it.each(['urlJob', 'isUrlHistoryValue', 'parseV4UrlRef', 'sealFetchedImage', 'imageUrlHash', 'publicUrlHash'])(
        'stops the fetch pod at startup when index.node has no %s',
        (missing) => {
            const nativePath = require.resolve('@posthog/ai-research-v4-native/index.node')
            jest.isolateModules(() => {
                jest.doMock(nativePath, () => {
                    const { [missing]: _missing, ...stale } = jest.requireActual(nativePath)
                    return stale
                })
                const { assertSharedRulesLoaded } = require('./v4-native')
                expect(() => assertSharedRulesLoaded()).toThrow('rebuild index.node')
            })
            jest.dontMock(nativePath)
        }
    )
})

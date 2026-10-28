import { isPublicHost, politenessKey, tryCanonicalizeUrl } from '@posthog/ai-research-v4-native'

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
})

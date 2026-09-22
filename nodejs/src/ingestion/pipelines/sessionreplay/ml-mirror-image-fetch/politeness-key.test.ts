import { politenessKey } from '@posthog/replay-anonymizer'

/**
 * The crate owns the rule and tests it. This file tests only that the fetch lane reaches that
 * function across the FFI boundary, so every case here asserts behaviour the crate already had.
 */
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

import { politenessKey } from './politeness-key'

describe('politenessKey', () => {
    it.each([['d111.cloudfront.net'], ['bucket.s3.amazonaws.com'], ['user.github.io'], ['myapp.vercel.app']])(
        'keeps %s as its own operator',
        (host) => {
            // These are the hosts the Rust politeness_key names. Each provider is a public suffix in
            // the private section of the list, so one tenant must not share a budget with another. The
            // default tldts options drop that section, which is the failure this pins.
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

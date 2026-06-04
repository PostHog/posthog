import { BARE_DOMAIN_REGEX, ensureAnchored } from './urlConfigLogic'

describe('urlConfigLogic helpers', () => {
    describe('ensureAnchored', () => {
        it.each([
            // bare domains become path-tolerant so a trailing slash or path still matches
            ['https://pineapple.co.za', '^https://pineapple.co.za(/.*)?$'],
            ['https://pineapple.co.za/', '^https://pineapple.co.za(/.*)?$'],
            ['https://example.com', '^https://example.com(/.*)?$'],
            ['http://example.com', '^http://example.com(/.*)?$'],
            ['example.com', '^example.com(/.*)?$'],
            // already anchored bare domains are normalized too (e.g. when editing an old trigger)
            ['^https://pineapple.co.za$', '^https://pineapple.co.za(/.*)?$'],
            // patterns with a path are left as an exact anchored match
            ['https://example.com/checkout', '^https://example.com/checkout$'],
            ['https://example.com/page.html', '^https://example.com/page.html$'],
            ['/checkout', '^/checkout$'],
            // patterns the user already made path-tolerant are kept as-is
            ['https://example.com(/.*)?', '^https://example.com(/.*)?$'],
            ['^https://example.com(/.*)?$', '^https://example.com(/.*)?$'],
        ])('anchors %s as %s', (input, expected) => {
            expect(ensureAnchored(input)).toEqual(expected)
        })

        it('produces a pattern that matches the domain and its sub-paths', () => {
            const regex = new RegExp(ensureAnchored('https://pineapple.co.za'))
            expect(regex.test('https://pineapple.co.za')).toBe(true)
            expect(regex.test('https://pineapple.co.za/')).toBe(true)
            expect(regex.test('https://pineapple.co.za/page')).toBe(true)
            expect(regex.test('https://pineapple.co.za/nested/path?q=1')).toBe(true)
            expect(regex.test('https://other.co.za')).toBe(false)
        })
    })

    describe('BARE_DOMAIN_REGEX', () => {
        it.each(['https://pineapple.co.za', 'https://example.com/', 'http://example.com', 'example.com'])(
            'treats %s as a bare domain',
            (url) => {
                expect(BARE_DOMAIN_REGEX.test(url)).toBe(true)
            }
        )

        it.each([
            'https://example.com/checkout',
            'https://example.com/page.html',
            '/checkout',
            'https://example.com(/.*)?',
        ])('does not treat %s as a bare domain', (url) => {
            expect(BARE_DOMAIN_REGEX.test(url)).toBe(false)
        })
    })
})

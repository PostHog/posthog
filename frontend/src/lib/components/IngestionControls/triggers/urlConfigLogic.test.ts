import {
    ensureAnchored,
    isLikelyUnmatchableUrlPattern,
    urlPatternMatchWarning,
} from 'lib/components/IngestionControls/triggers/urlConfigLogic'

describe('urlConfigLogic helpers', () => {
    describe('ensureAnchored', () => {
        it.each([
            ['example.com', '^example.com$'],
            ['^example.com', '^example.com$'],
            ['example.com$', '^example.com$'],
            ['^example.com$', '^example.com$'],
            ['^/checkout$', '^/checkout$'],
            ['https?://example\\.com(/.*)?', '^https?://example\\.com(/.*)?$'],
        ])('wraps %s with anchors -> %s', (input, expected) => {
            expect(ensureAnchored(input)).toEqual(expected)
        })
    })

    describe('isLikelyUnmatchableUrlPattern', () => {
        it.each([
            'www.danzpodio.com',
            '^www.danzpodio.com$',
            'example.com',
            '^example.com$',
            'sub.domain.example.co.uk',
            '^sub.domain.example.co.uk$',
            '^example.com/$',
        ])('flags bare hostname %s as unmatchable', (input) => {
            expect(isLikelyUnmatchableUrlPattern(input)).toBe(true)
        })

        it.each([
            '',
            '/checkout',
            '^/checkout$',
            'https://example.com',
            '^https://example.com$',
            '^https?://example\\.com(/.*)?$',
            'example.com/page',
            '^example.com/admin.*$',
            'localhost',
            'foo',
        ])('does not flag %s', (input) => {
            expect(isLikelyUnmatchableUrlPattern(input)).toBe(false)
        })
    })

    describe('urlPatternMatchWarning', () => {
        it('returns a warning for inputs ending in a TLD', () => {
            const warning = urlPatternMatchWarning('www.danzpodio.com')
            expect(warning).toContain('include the protocol')
            expect(warning).toContain('www.danzpodio.com')
            expect(warning).toContain('(/.*)?')
        })

        it('returns a warning for inputs ending in a TLD followed by slash', () => {
            const warning = urlPatternMatchWarning('www.danzpodio.com/')
            expect(warning).not.toBeNull()
            expect(warning).toContain('www.danzpodio.com')
        })

        it('returns null for empty input', () => {
            expect(urlPatternMatchWarning('')).toBeNull()
        })

        it('returns null for inputs with a path', () => {
            expect(urlPatternMatchWarning('https://example.com/page')).toBeNull()
        })

        it('returns null for path-only patterns', () => {
            expect(urlPatternMatchWarning('^/checkout$')).toBeNull()
        })
    })
})

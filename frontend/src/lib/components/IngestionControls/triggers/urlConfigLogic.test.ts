import { anchoredUrlCanMatchUrl, ensureAnchored, getUrlPatternWarning } from './urlConfigLogic'

describe('urlConfigLogic helpers', () => {
    describe('anchoredUrlCanMatchUrl', () => {
        it.each<[string, boolean]>([
            // Screen-name and path patterns can never match once anchored to the full URL.
            ['Jagex Launcher/.*', false],
            ['/checkout/.*', false],
            ['dashboard/settings', false],
            // Patterns that line up with a scheme or start flexibly can match.
            ['https://example.com/', true],
            ['^https://example.com/page$', true],
            ['.*checkout.*', true],
            ['(app|https)://.*', true],
            ['http', true],
            ['', true],
        ])('%s -> %s', (url, expected) => {
            expect(anchoredUrlCanMatchUrl(url)).toBe(expected)
        })
    })

    describe('getUrlPatternWarning', () => {
        it('warns that an anchored path pattern cannot match a URL', () => {
            expect(getUrlPatternWarning('Jagex Launcher/.*')).toContain("can't match a URL")
        })

        it('gives domain guidance for a bare domain', () => {
            expect(getUrlPatternWarning('https://example.com')).toContain('(/.*)?')
        })

        it('does not warn for a scheme-anchored pattern', () => {
            expect(getUrlPatternWarning('^https://example.com/page$')).toBeNull()
        })

        it('does not warn for an empty pattern', () => {
            expect(getUrlPatternWarning('')).toBeNull()
        })
    })

    describe('ensureAnchored', () => {
        it.each<[string, string]>([
            ['example', '^example$'],
            ['^example', '^example$'],
            ['example$', '^example$'],
            ['^example$', '^example$'],
        ])('%s -> %s', (url, expected) => {
            expect(ensureAnchored(url)).toBe(expected)
        })
    })
})

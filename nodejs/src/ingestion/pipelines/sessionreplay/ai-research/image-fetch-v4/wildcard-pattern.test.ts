import { wildcardPatternMatchesPathname } from './wildcard-pattern'

describe('wildcardPatternMatchesPathname', () => {
    it.each([
        ['a prefix', '/images/', '/images/photo.png', true],
        ['an exact path', '/images/photo.png$', '/images/photo.png', true],
        ['an exact path mismatch', '/images/photo.png$', '/images/photo.png/preview', false],
        ['a middle wildcard', '/images/*/preview$', '/images/v1/preview', true],
        ['an anchored suffix mismatch', '/images/*/preview$', '/images/v1/preview/more', false],
        ['a leading wildcard', '*/private/*', '/v1/private/image.png', true],
        ['literal regular expression characters', '/literal.+(item)$', '/literal.+(item)', true],
        ['an unreserved percent encoding', '/asset%7Ename$', '/asset~name', true],
        ['consecutive wildcards', '/asset/**/preview$', '/asset//preview', true],
        ['overlapping anchored segments', '*a*a$', '/aaa', true],
    ])('matches %s', (_name, pattern, pathname, expected) => {
        expect(wildcardPatternMatchesPathname(pattern, pathname)).toBe(expected)
    })

    it('does not compile wildcard patterns as regular expressions', () => {
        const regexpConstructor = jest.spyOn(globalThis, 'RegExp').mockReturnValue(/$a/)
        try {
            expect(wildcardPatternMatchesPathname(`${'*a'.repeat(64)}*b$`, `/${'a'.repeat(128)}c`)).toBe(false)
            expect(regexpConstructor).not.toHaveBeenCalled()
        } finally {
            regexpConstructor.mockRestore()
        }
    })
})

import { compilePattern, findMatches } from './regexTesterLogic'

describe('regexTesterLogic', () => {
    // RE2JS types start/end as strings; if the numeric conversion is dropped the popover slices
    // the sample with string offsets and highlights nothing.
    it('returns every match with its capture groups', () => {
        expect(findMatches('/blog/([0-9]{4})/', 'a /blog/2024/ b /blog/1999/')).toEqual([
            { start: 2, end: 13, groups: ['2024'] },
            { start: 16, end: 27, groups: ['1999'] },
        ])
    })

    it('reports groups that did not participate as null', () => {
        expect(findMatches('(a)|(b)', 'b')).toEqual([{ start: 0, end: 1, groups: [null, 'b'] }])
    })

    it('terminates on a pattern that matches empty strings', () => {
        expect(findMatches('x*', 'abxxc')).toHaveLength(5)
    })

    it.each([
        // An empty pattern matches at every offset, which is noise rather than a result.
        ['an empty pattern', '', 'anything'],
        // Compiling throws, and an unguarded throw takes the whole popover down.
        ['a pattern RE2 rejects', '(?=lookahead)', 'anything'],
    ])('returns no matches for %s', (_name, pattern, value) => {
        expect(findMatches(pattern, value)).toEqual([])
    })

    it('accepts a pattern RE2 supports', () => {
        expect(compilePattern('^/blog/[0-9]{4}/')).toBeNull()
    })

    // Swapping RE2 for JS RegExp here would accept syntax ClickHouse rejects at query time.
    it('explains why RE2 rejects lookahead', () => {
        expect(compilePattern('(?=lookahead)')).toContain('Lookahead')
    })
})

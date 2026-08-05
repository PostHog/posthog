import { findRegexLiterals } from './findRegexLiterals'

describe('findRegexLiterals', () => {
    const patternsIn = (text: string): string[] => findRegexLiterals(text).map((literal) => literal.pattern)

    it('returns the offsets of the pattern inside the quotes', () => {
        const sql = "SELECT match(properties.$current_url, '/blog/')"
        const [literal] = findRegexLiterals(sql)

        expect(sql.slice(literal.start, literal.end)).toEqual('/blog/')
    })

    // Each row asserts the *complete* list, so a row also proves the other arguments — the
    // haystack, the replacement — were left alone.
    it.each([
        ['match', "SELECT match(url, '/blog/[0-9]{4}/')", ['/blog/[0-9]{4}/']],
        ['extract', "SELECT extract(url, 'utm_source=([^&]*)')", ['utm_source=([^&]*)']],
        ['countMatches', "SELECT countMatches(url, '/product/')", ['/product/']],
        ['replaceRegexpAll', "SELECT replaceRegexpAll(url, '/[0-9]+/', '/:id/')", ['/[0-9]+/']],
        ['splitByRegexp', "SELECT splitByRegexp('\\s+', url)", ['\\s+']],
        ['case-insensitive names', "SELECT MATCH(url, '^/docs')", ['^/docs']],
        ['the regex operator', "SELECT 1 WHERE url =~ '^/blog'", ['^/blog']],
        ['the negated regex operator', "SELECT 1 WHERE url !~ '^/internal'", ['^/internal']],
        ['an array of patterns', "SELECT multiMatchAny(url, ['^/blog', '^/docs'])", ['^/blog', '^/docs']],
        ['nested calls', "SELECT match(lower(concat(a, b)), '^/blog')", ['^/blog']],
    ])('finds the pattern for %s', (_name, sql, expected) => {
        expect(patternsIn(sql)).toEqual(expected)
    })

    it.each([
        ['plain equality', "SELECT 1 WHERE url = '/blog/'"],
        ['non-regex functions', "SELECT concat('a', 'b')"],
        ['line comments', "-- match(url, '/blog/')\nSELECT 1"],
        ['block comments', "/* match(url, '/blog/') */ SELECT 1"],
        // Underlining from the opening quote to the end of the document while someone types.
        ['unterminated literals', "SELECT match(url, '/blog/"],
    ])('finds nothing in %s', (_name, sql) => {
        expect(patternsIn(sql)).toEqual([])
    })

    it('resolves SQL escapes but leaves regex escapes alone', () => {
        expect(patternsIn("SELECT match(url, '\\\\d+ isn''t \\d+')")).toEqual(["\\d+ isn't \\d+"])
    })
})

import {
    applyPathCleaning,
    applyPathCleaningRule,
    canPreviewPathCleaningRegex,
    expandAlias,
    isValidPathCleaningRegex,
    pathCleaningRegexError,
} from './pathCleaningUtils'

// [name, alias, groups (index 0 is the whole match), expected]
const EXPAND_CASES: [string, string, (string | undefined)[], string][] = [
    ['group reference', '/u/\\1', ['/users/42', '42'], '/u/42'],
    ['whole-match reference', '[\\0]', ['/users/42', '42'], '[/users/42]'],
    ['escaped backslash before a digit is literal', '\\\\1', ['/users/42', '42'], '\\1'],
    // ClickHouse emits `$` verbatim, so the preview must not read it as a group reference.
    ['dollar stays literal', '/u/$1', ['/users/42', '42'], '/u/$1'],
    // re2 has no `\10` — it reads group 1 then a literal `0`, where JS `$10` would take group 10.
    ['two-digit reference is group 1 then a literal', '\\10', ['ab', 'a', 'b'], 'a0'],
    ['group the pattern never filled substitutes as empty', '/u/\\2', ['/users/42', '42', undefined], '/u/'],
]

describe('pathCleaningUtils', () => {
    it.each(EXPAND_CASES)('expandAlias: %s', (_name, alias, groups, expected) => {
        expect(expandAlias(alias, groups)).toBe(expected)
    })

    it.each([
        // Reuses capture group 1, matching what ClickHouse replaceRegexpAll does on the backend.
        ['keeps a captured id', '/users/42/profile', '/users/(\\d+)/profile', '/users/\\1', '/users/42'],
        [
            'captures leading segments and drops the hash',
            '/a/b/c/#random',
            '^(/[^/#]+/[^/#]+/[^/#]+)/#.*$',
            '\\1',
            '/a/b/c',
        ],
        // A `$1` alias is a literal in ClickHouse, so the preview must not treat it as a group ref.
        ['dollar-one is not a group reference', '/users/42', '/users/(\\d+)', '/u/$1', '/u/$1'],
        // With ten groups in play, a JS `$10` replacement string would wrongly resolve to group 10.
        [
            'two-digit reference resolves against re2 rules, not JavaScript ones',
            'abcdefghij',
            '(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)',
            '\\10',
            'a0',
        ],
        // re2 is case-sensitive, so a case-mismatched rule must not clean here either — otherwise the
        // preview promises a cleaning the query never performs.
        ['case mismatch does not match', '/users/42', '/Users/(\\d+)', '/u/\\1', '/users/42'],
        // `(?i)` is how re2 opts into case-insensitive matching, and JavaScript rejects it inline.
        ['a (?i) prefix matches case-insensitively', '/users/42', '(?i)/Users/(\\d+)', '/u/\\1', '/u/42'],
    ])('applyPathCleaningRule: %s', (_name, path, regex, alias, expected) => {
        expect(applyPathCleaningRule(path, { regex, alias })).toBe(expected)
    })

    it('skips invalid or empty regexes without throwing', () => {
        expect(applyPathCleaningRule('/x', { regex: '(', alias: '/y' })).toBe('/x')
        expect(applyPathCleaningRule('/x', { regex: '', alias: '/y' })).toBe('/x')
        expect(applyPathCleaningRule('/x', { regex: '(?i)', alias: '/y' })).toBe('/x')
    })

    it.each([
        // `(?i)` is how re2 asks for case-insensitive matching, and JavaScript rejects it outright, so
        // validating with JavaScript would call a documented, working rule invalid.
        ['an inline (?i) flag group is valid', '(?i)/Users/(\\d+)', true],
        ['a plain pattern is valid', '/users/(\\d+)', true],
        // The reverse direction: JavaScript accepts lookahead and re2 has no support for it, so
        // validating with JavaScript would enable Save and leave the backend to reject the rule.
        ['a lookahead is rejected', '/api(?!/internal)/', false],
        ['an unclosed group is rejected', '(', false],
        // ClickHouse `replaceRegexpAll` matches an empty pattern at every position, so the backend
        // refuses a rule without a regex too.
        ['an empty regex is rejected', '', false],
    ])('isValidPathCleaningRegex: %s', (_name, regex, expected) => {
        expect(isValidPathCleaningRegex(regex)).toBe(expected)
    })

    it('sends a capture-group reference in the regex to the alias', () => {
        expect(pathCleaningRegexError('/user/(\\d+)/\\1')).toContain('alias')
    })

    it('separates a regex the query can run from one the preview can run', () => {
        // re2 spells a named group `(?P<id>...)`, which JavaScript has no equivalent for. The rule
        // cleans paths in the query, so the preview has to report that it can't show it rather than
        // report that the rule didn't match.
        expect(isValidPathCleaningRegex('(?P<id>\\d+)')).toBe(true)
        expect(canPreviewPathCleaningRegex('(?P<id>\\d+)')).toBe(false)
        expect(canPreviewPathCleaningRegex('/users/(\\d+)')).toBe(true)
    })

    it('chains rules in order, each feeding the next', () => {
        const filters = [
            { regex: '/users/(\\d+)/.*', alias: '/users/\\1' },
            { regex: '/users/42', alias: '/users/me' },
        ]
        expect(applyPathCleaning('/users/42/settings', filters)).toBe('/users/me')
    })
})

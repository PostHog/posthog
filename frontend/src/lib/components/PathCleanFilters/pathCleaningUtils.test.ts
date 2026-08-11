import { applyPathCleaning, applyPathCleaningRule, expandAlias } from './pathCleaningUtils'

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

    it('chains rules in order, each feeding the next', () => {
        const filters = [
            { regex: '/users/(\\d+)/.*', alias: '/users/\\1' },
            { regex: '/users/42', alias: '/users/me' },
        ]
        expect(applyPathCleaning('/users/42/settings', filters)).toBe('/users/me')
    })
})

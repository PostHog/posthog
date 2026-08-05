import { aliasToJsReplacement, applyPathCleaning, applyPathCleaningRule } from './pathCleaningUtils'

describe('pathCleaningUtils', () => {
    it.each([
        ['group back-reference', '\\1', '$1'],
        ['whole-match reference', '\\0', '$&'],
        ['literal dollar is escaped', 'price$', 'price$$'],
        ['dollar-one stays literal', '/u/$1', '/u/$$1'],
        ['escaped backslash before a digit is literal', '\\\\1', '\\1'],
    ])('aliasToJsReplacement: %s', (_name, alias, expected) => {
        expect(aliasToJsReplacement(alias)).toBe(expected)
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
        ['dollar-one is not a back-reference', '/users/42', '/users/(\\d+)', '/u/$1', '/u/$1'],
    ])('applyPathCleaningRule: %s', (_name, path, regex, alias, expected) => {
        expect(applyPathCleaningRule(path, { regex, alias })).toBe(expected)
    })

    it('skips invalid or empty regexes without throwing', () => {
        expect(applyPathCleaningRule('/x', { regex: '(', alias: '/y' })).toBe('/x')
        expect(applyPathCleaningRule('/x', { regex: '', alias: '/y' })).toBe('/x')
    })

    it('chains rules in order, each feeding the next', () => {
        const filters = [
            { regex: '/users/(\\d+)/.*', alias: '/users/\\1' },
            { regex: '/users/42', alias: '/users/me' },
        ]
        expect(applyPathCleaning('/users/42/settings', filters)).toBe('/users/me')
    })
})

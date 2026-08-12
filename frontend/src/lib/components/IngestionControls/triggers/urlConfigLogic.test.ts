import { UrlPatternTestRow, ensureAnchored, testUrlAgainstPatterns } from './urlConfigLogic'

describe('urlConfigLogic helpers', () => {
    describe('testUrlAgainstPatterns', () => {
        it.each<[string, string, string[], string | null, UrlPatternTestRow[]]>([
            [
                'saved pattern matches the URL',
                'https://example.com/page',
                ['^https://example.com/page$'],
                null,
                [{ pattern: '^https://example.com/page$', status: 'match', inProgress: false }],
            ],
            [
                'valid saved pattern that does not match',
                'https://example.com/other',
                ['^https://example.com/page$'],
                null,
                [{ pattern: '^https://example.com/page$', status: 'no-match', inProgress: false }],
            ],
            [
                'uncompilable stored glob reports invalid, not no-match',
                'https://app.example.com/staff/list',
                ['^*app.example.com/staff/*$'],
                null,
                [{ pattern: '^*app.example.com/staff/*$', status: 'invalid', inProgress: false }],
            ],
            [
                'in-progress input is anchored the same way it saves and matches',
                'example.com/page',
                [],
                'example.com/page',
                [{ pattern: '^example.com/page$', status: 'match', inProgress: true }],
            ],
            [
                'in-progress glob is reported invalid once anchored',
                'https://app.example.com/staff',
                [],
                '*app.example.com/staff/*',
                [{ pattern: '^*app.example.com/staff/*$', status: 'invalid', inProgress: true }],
            ],
            [
                'blank in-progress input adds no row',
                'https://example.com/page',
                ['^https://example.com/page$'],
                '   ',
                [{ pattern: '^https://example.com/page$', status: 'match', inProgress: false }],
            ],
        ])('%s', (_description, testUrl, savedPatterns, inProgress, expected) => {
            expect(testUrlAgainstPatterns(testUrl, savedPatterns, inProgress)).toEqual(expected)
        })
    })

    describe('ensureAnchored', () => {
        it.each([
            ['bare pattern', 'example.com/page', '^example.com/page$'],
            ['already anchored', '^example.com/page$', '^example.com/page$'],
        ])('%s', (_description, input, expected) => {
            expect(ensureAnchored(input)).toBe(expected)
        })
    })
})

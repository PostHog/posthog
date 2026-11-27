import * as regexp from 'lib/utils/regexp'

import { getRegexFilterPatterns, hasInvalidRegexPattern } from './hasInvalidRegexFilter'

const nestedQuery = (operator: string, value: unknown): Record<string, unknown> => ({
    kind: 'TrendsQuery',
    series: [{ kind: 'EventsNode', event: '$pageview', properties: [{ operator: 'exact', value: 'ok' }] }],
    properties: { type: 'AND', values: [{ type: 'OR', values: [{ operator, value }] }] },
})

describe('hasInvalidRegexFilter', () => {
    it.each([
        ['valid regex in property filter', { operator: 'regex', value: 'test.*' }, ['test.*'], false],
        ['valid not_regex in property filter', { operator: 'not_regex', value: '^foo$' }, ['^foo$'], false],
        ['invalid regex - lookahead', { operator: 'regex', value: '(?=test)' }, ['(?=test)'], true],
        ['invalid regex - unclosed bracket', { operator: 'regex', value: '[unclosed' }, ['[unclosed'], true],
        ['invalid not_regex - backreference', { operator: 'not_regex', value: '(test)\\1' }, ['(test)\\1'], true],
        ['non-regex operator with invalid pattern is ok', { operator: 'exact', value: '(?=test)' }, [], false],
        ['regex operator with non-string value', { operator: 'regex', value: 123 }, [], false],
        ['empty object', {}, [], false],
        ['null', null, [], false],
        ['string', 'test', [], false],
        ['number', 42, [], false],
        [
            'invalid regex nested in arrays',
            [
                { operator: 'exact', value: 'ok' },
                { operator: 'regex', value: '(?=bad)' },
            ],
            ['(?=bad)'],
            true,
        ],
        ['invalid regex deeply nested in a query', nestedQuery('regex', '(?=lookahead)'), ['(?=lookahead)'], true],
        ['valid regex deeply nested in a query', nestedQuery('regex', 'valid.*pattern'), ['valid.*pattern'], false],
        [
            'one invalid pattern among several filters',
            [
                { type: 'event', key: 'url', operator: 'regex', value: '^/valid/' },
                { type: 'event', key: 'path', operator: 'not_regex', value: '(?!invalid)' },
            ],
            ['^/valid/', '(?!invalid)'],
            true,
        ],
    ])('%s', async (_name, input, expectedPatterns, expectedInvalid) => {
        const patterns = getRegexFilterPatterns(input)

        expect(patterns).toEqual(expectedPatterns)
        expect(await hasInvalidRegexPattern(patterns)).toBe(expectedInvalid)
    })

    it('lets the query run when the RE2 engine fails to load', async () => {
        jest.spyOn(regexp, 'loadRE2').mockRejectedValueOnce(new Error('Failed to fetch dynamically imported module'))

        expect(await hasInvalidRegexPattern(['(?=lookahead)'])).toBe(false)
    })
})

import { NodeKind } from '~/queries/schema/schema-general'

import { hasInvalidRegexFilter, validateQuery } from './queryUtils'

describe('hasInvalidRegexFilter', () => {
    it.each([
        ['valid regex in property filter', { operator: 'regex', value: 'test.*' }, false],
        ['valid not_regex in property filter', { operator: 'not_regex', value: '^foo$' }, false],
        ['invalid regex - lookahead', { operator: 'regex', value: '(?=test)' }, true],
        ['invalid regex - unclosed bracket', { operator: 'regex', value: '[unclosed' }, true],
        ['invalid not_regex - backreference', { operator: 'not_regex', value: '(test)\\1' }, true],
        ['non-regex operator with invalid pattern is ok', { operator: 'exact', value: '(?=test)' }, false],
        ['regex operator with non-string value', { operator: 'regex', value: 123 }, false],
        ['empty object', {}, false],
        ['null', null, false],
        ['string', 'test', false],
        ['number', 42, false],
    ])('%s', (_name, input, expected) => {
        expect(hasInvalidRegexFilter(input)).toBe(expected)
    })

    it('finds invalid regex nested in arrays', () => {
        const nested = [
            { operator: 'exact', value: 'ok' },
            { operator: 'regex', value: '(?=bad)' },
        ]
        expect(hasInvalidRegexFilter(nested)).toBe(true)
    })

    it('finds invalid regex deeply nested in objects', () => {
        const deeplyNested = {
            properties: {
                type: 'AND',
                values: [
                    {
                        type: 'OR',
                        values: [{ operator: 'regex', value: '(?=lookahead)' }],
                    },
                ],
            },
        }
        expect(hasInvalidRegexFilter(deeplyNested)).toBe(true)
    })

    it('returns false for valid regex deeply nested', () => {
        const deeplyNested = {
            properties: {
                type: 'AND',
                values: [
                    {
                        type: 'OR',
                        values: [{ operator: 'regex', value: 'valid.*pattern' }],
                    },
                ],
            },
        }
        expect(hasInvalidRegexFilter(deeplyNested)).toBe(false)
    })

    it('handles query-like structure with multiple property filters', () => {
        const queryLike = {
            kind: 'TrendsQuery',
            series: [
                {
                    kind: 'EventsNode',
                    event: '$pageview',
                    properties: [
                        { type: 'event', key: 'url', operator: 'regex', value: '^/valid/' },
                        { type: 'event', key: 'path', operator: 'not_regex', value: '(?!invalid)' },
                    ],
                },
            ],
        }
        expect(hasInvalidRegexFilter(queryLike)).toBe(true)
    })
})

describe('validateQuery', () => {
    it('returns false for funnels with less than 2 steps', () => {
        const funnelQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
        }
        expect(validateQuery(funnelQuery)).toBe(false)
    })

    it('returns true for funnels with 2+ steps', () => {
        const funnelQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [
                { kind: NodeKind.EventsNode, event: '$pageview' },
                { kind: NodeKind.EventsNode, event: '$signup' },
            ],
        }
        expect(validateQuery(funnelQuery)).toBe(true)
    })

    it('returns false for query with invalid regex property filter', () => {
        const trendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            properties: [{ type: 'event', key: 'url', operator: 'regex', value: '(?=lookahead)' }],
        }
        expect(validateQuery(trendsQuery)).toBe(false)
    })

    it('returns true for query with valid regex property filter', () => {
        const trendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            properties: [{ type: 'event', key: 'url', operator: 'regex', value: '^/api/.*' }],
        }
        expect(validateQuery(trendsQuery)).toBe(true)
    })

    it('returns true for query without regex filters', () => {
        const trendsQuery = {
            kind: NodeKind.TrendsQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            properties: [{ type: 'event', key: 'url', operator: 'exact', value: '/home' }],
        }
        expect(validateQuery(trendsQuery)).toBe(true)
    })
})

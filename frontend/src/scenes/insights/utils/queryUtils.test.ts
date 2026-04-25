import { NodeKind } from '~/queries/schema/schema-general'

import {
    filterVariablesReferencedInQuery,
    hasInvalidRegexFilter,
    isBoxPlotMissingProperty,
    syncSelectedVariablesToQuery,
    validateQuery,
} from './queryUtils'

const AVAILABLE_VARIABLES = [
    { id: 'date-id', code_name: 'date' },
    { id: 'product-id', code_name: 'product' },
    { id: 'region-id', code_name: 'region' },
]

describe('filterVariablesReferencedInQuery', () => {
    it('keeps only variables referenced in the current query', () => {
        expect(
            filterVariablesReferencedInQuery(
                'SELECT {variables.date}, {variables.date} FROM events WHERE product = {variables.product}',
                AVAILABLE_VARIABLES
            )
        ).toEqual([
            { id: 'date-id', code_name: 'date' },
            { id: 'product-id', code_name: 'product' },
        ])
    })
})

describe('syncSelectedVariablesToQuery', () => {
    it('removes stale selected variables while preserving values for ones still in use', () => {
        expect(
            syncSelectedVariablesToQuery(
                'SELECT * FROM events WHERE timestamp >= {variables.date}',
                AVAILABLE_VARIABLES,
                [
                    { variableId: 'date-id', code_name: 'date', value: '2026-01-01' },
                    { variableId: 'product-id', code_name: 'product', value: 'mobile' },
                ]
            )
        ).toEqual([{ variableId: 'date-id', code_name: 'date', value: '2026-01-01' }])
    })

    it('adds newly referenced variables once, in query order', () => {
        expect(
            syncSelectedVariablesToQuery(
                'SELECT * FROM events WHERE product = {variables.product} AND region = {variables.region} AND product = {variables.product}',
                AVAILABLE_VARIABLES,
                [{ variableId: 'date-id', code_name: 'date', value: '2026-01-01' }]
            )
        ).toEqual([
            { variableId: 'product-id', code_name: 'product' },
            { variableId: 'region-id', code_name: 'region' },
        ])
    })
})

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

    it('returns false for funnels with incomplete data warehouse step', () => {
        const funnelQuery = {
            kind: NodeKind.FunnelsQuery,
            series: [
                {
                    kind: NodeKind.FunnelsDataWarehouseNode,
                    table_name: 'events_table',
                    id_field: 'person_id',
                    timestamp_field: 'timestamp',
                },
                { kind: NodeKind.EventsNode, event: '$signup' },
            ],
        }
        expect(validateQuery(funnelQuery)).toBe(false)
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

describe('isBoxPlotMissingProperty', () => {
    it('returns true when there are no series', () => {
        expect(isBoxPlotMissingProperty([])).toBe(true)
    })

    it('returns true when a series is missing math_property', () => {
        expect(
            isBoxPlotMissingProperty([
                { kind: NodeKind.EventsNode, event: '$pageview', math_property: 'duration' },
                { kind: NodeKind.EventsNode, event: '$signup' },
            ])
        ).toBe(true)
    })

    it('returns false when all series have math_property', () => {
        expect(
            isBoxPlotMissingProperty([
                { kind: NodeKind.EventsNode, event: '$pageview', math_property: 'duration' },
                { kind: NodeKind.EventsNode, event: '$signup', math_property: 'revenue' },
            ])
        ).toBe(false)
    })
})

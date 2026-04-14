import { InsightQueryNode, NodeKind } from '~/queries/schema/schema-general'

import {
    filterVariablesReferencedInQuery,
    hasInvalidRegexFilter,
    isBoxPlotMissingProperty,
    stripUnsupportedQueryFields,
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

describe('stripUnsupportedQueryFields', () => {
    it.each([
        [
            'strips breakdownFilter from StickinessQuery',
            {
                kind: NodeKind.StickinessQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                breakdownFilter: { breakdown: '$browser' },
            },
            {},
            ['breakdownFilter'],
        ],
        [
            'strips breakdownFilter from LifecycleQuery',
            {
                kind: NodeKind.LifecycleQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                breakdownFilter: { breakdown: '$browser' },
            },
            {},
            ['breakdownFilter'],
        ],
        [
            'strips breakdownFilter from PathsQuery',
            {
                kind: NodeKind.PathsQuery,
                pathsFilter: { includeEventTypes: [] },
                breakdownFilter: { breakdown: '$browser' },
            },
            {},
            ['breakdownFilter'],
        ],
        [
            'preserves breakdownFilter on TrendsQuery',
            {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                breakdownFilter: { breakdown: '$browser' },
            },
            { breakdownFilter: { breakdown: '$browser' } },
            [],
        ],
        [
            'preserves breakdownFilter on FunnelsQuery',
            {
                kind: NodeKind.FunnelsQuery,
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview' },
                    { kind: NodeKind.EventsNode, event: '$signup' },
                ],
                breakdownFilter: { breakdown: '$browser' },
            },
            { breakdownFilter: { breakdown: '$browser' } },
            [],
        ],
        [
            'preserves breakdownFilter on RetentionQuery',
            {
                kind: NodeKind.RetentionQuery,
                retentionFilter: {},
                breakdownFilter: { breakdown: '$browser' },
            },
            { breakdownFilter: { breakdown: '$browser' } },
            [],
        ],
        [
            'strips compareFilter from FunnelsQuery',
            {
                kind: NodeKind.FunnelsQuery,
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview' },
                    { kind: NodeKind.EventsNode, event: '$signup' },
                ],
                compareFilter: { compare: true },
            },
            {},
            ['compareFilter'],
        ],
        [
            'strips compareFilter from LifecycleQuery',
            {
                kind: NodeKind.LifecycleQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                compareFilter: { compare: true },
            },
            {},
            ['compareFilter'],
        ],
        [
            'preserves compareFilter on TrendsQuery',
            {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                compareFilter: { compare: true },
            },
            { compareFilter: { compare: true } },
            [],
        ],
        [
            'preserves compareFilter on StickinessQuery',
            {
                kind: NodeKind.StickinessQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                compareFilter: { compare: true },
            },
            { compareFilter: { compare: true } },
            [],
        ],
        [
            'strips funnelPathsFilter from TrendsQuery',
            {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                funnelPathsFilter: { funnelSource: {} },
            },
            {},
            ['funnelPathsFilter'],
        ],
        [
            'preserves funnelPathsFilter on PathsQuery',
            {
                kind: NodeKind.PathsQuery,
                pathsFilter: { includeEventTypes: [] },
                funnelPathsFilter: { funnelSource: {} },
            },
            { funnelPathsFilter: { funnelSource: {} } },
            [],
        ],
        [
            'preserves all supported fields on TrendsQuery',
            {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                breakdownFilter: { breakdown: '$browser' },
                compareFilter: { compare: true },
            },
            { breakdownFilter: { breakdown: '$browser' }, compareFilter: { compare: true } },
            [],
        ],
        [
            'strips compareFilter but preserves breakdownFilter on FunnelsQuery',
            {
                kind: NodeKind.FunnelsQuery,
                series: [
                    { kind: NodeKind.EventsNode, event: '$pageview' },
                    { kind: NodeKind.EventsNode, event: '$signup' },
                ],
                breakdownFilter: { breakdown: '$browser' },
                compareFilter: { compare: true },
            },
            { breakdownFilter: { breakdown: '$browser' } },
            ['compareFilter'],
        ],
    ])('%s', (_name, input, expectedPresent, expectedAbsent) => {
        const result = stripUnsupportedQueryFields(input as InsightQueryNode)

        expect(result).toEqual(expect.objectContaining(expectedPresent))
        for (const field of expectedAbsent) {
            expect(result).not.toHaveProperty(field)
        }
    })

    it('does not mutate the original query', () => {
        const original = {
            kind: NodeKind.StickinessQuery,
            series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
            breakdownFilter: { breakdown: '$browser' },
        }

        stripUnsupportedQueryFields(original as unknown as InsightQueryNode)

        expect(original.breakdownFilter).toEqual({ breakdown: '$browser' })
    })

    describe('formula fields', () => {
        it.each([
            [NodeKind.FunnelsQuery, 'funnelsFilter'],
            [NodeKind.StickinessQuery, 'stickinessFilter'],
            [NodeKind.RetentionQuery, 'retentionFilter'],
            [NodeKind.PathsQuery, 'pathsFilter'],
            [NodeKind.LifecycleQuery, 'lifecycleFilter'],
        ])('strips formula/formulas/formulaNodes from %s.%s', (kind, filterKey) => {
            const input = {
                kind,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                [filterKey]: {
                    formula: 'A+B',
                    formulas: ['A+B'],
                    formulaNodes: [{ formula: 'A+B', custom_name: 'Sum' }],
                    someValidField: 'keep-me',
                },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result[filterKey].formula).toBeUndefined()
            expect(result[filterKey].formulas).toBeUndefined()
            expect(result[filterKey].formulaNodes).toBeUndefined()
            expect(result[filterKey].someValidField).toBe('keep-me')
        })

        it('preserves formula fields on TrendsQuery.trendsFilter', () => {
            const input = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                trendsFilter: {
                    formula: 'A+B',
                    formulaNodes: [{ formula: 'A+B' }],
                },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result.trendsFilter.formula).toBe('A+B')
            expect(result.trendsFilter.formulaNodes).toEqual([{ formula: 'A+B' }])
        })
    })

    describe('display field', () => {
        it.each([
            [NodeKind.FunnelsQuery, 'funnelsFilter'],
            [NodeKind.PathsQuery, 'pathsFilter'],
            [NodeKind.LifecycleQuery, 'lifecycleFilter'],
        ])('strips display from %s.%s', (kind, filterKey) => {
            const input = {
                kind,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                [filterKey]: { display: 'ActionsLineGraph', someValidField: 'keep-me' },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result[filterKey].display).toBeUndefined()
            expect(result[filterKey].someValidField).toBe('keep-me')
        })

        it.each([
            [NodeKind.TrendsQuery, 'trendsFilter'],
            [NodeKind.RetentionQuery, 'retentionFilter'],
            [NodeKind.StickinessQuery, 'stickinessFilter'],
        ])('preserves display on %s.%s', (kind, filterKey) => {
            const input = {
                kind,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                [filterKey]: { display: 'ActionsLineGraph' },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result[filterKey].display).toBe('ActionsLineGraph')
        })
    })

    describe('selectedInterval field', () => {
        it.each([
            [NodeKind.TrendsQuery, 'trendsFilter'],
            [NodeKind.FunnelsQuery, 'funnelsFilter'],
            [NodeKind.StickinessQuery, 'stickinessFilter'],
        ])('strips selectedInterval from %s.%s', (kind, filterKey) => {
            const input = {
                kind,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                [filterKey]: { selectedInterval: 7 },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result[filterKey].selectedInterval).toBeUndefined()
        })

        it('preserves selectedInterval on RetentionQuery.retentionFilter', () => {
            const input = {
                kind: NodeKind.RetentionQuery,
                retentionFilter: { selectedInterval: 7 },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result.retentionFilter.selectedInterval).toBe(7)
        })
    })

    describe('TrendsFilter-specific invalid fields', () => {
        it('strips chartSettings and totalIntervals from trendsFilter', () => {
            const input = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                trendsFilter: {
                    chartSettings: { foo: 'bar' },
                    totalIntervals: 14,
                    display: 'ActionsLineGraph',
                },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result.trendsFilter.chartSettings).toBeUndefined()
            expect(result.trendsFilter.totalIntervals).toBeUndefined()
            expect(result.trendsFilter.display).toBe('ActionsLineGraph')
        })
    })

    describe('legacy top-level query fields', () => {
        it('strips breakdown, full, limit, cohort from TrendsQuery top level', () => {
            const input = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                breakdown: { property: '$browser' },
                full: true,
                limit: 100,
                cohort: 42,
                breakdownFilter: { breakdown: '$os' },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result.breakdown).toBeUndefined()
            expect(result.full).toBeUndefined()
            expect(result.limit).toBeUndefined()
            expect(result.cohort).toBeUndefined()
            // breakdownFilter — the valid modern location — is preserved
            expect(result.breakdownFilter).toEqual({ breakdown: '$os' })
        })

        it('strips funnelWindowDays from FunnelsQuery top level', () => {
            const input = {
                kind: NodeKind.FunnelsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                funnelWindowDays: 14,
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result.funnelWindowDays).toBeUndefined()
        })
    })

    describe('breakdownFilter invalid fields', () => {
        it('strips limit from breakdownFilter (schema uses breakdown_limit)', () => {
            const input = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                breakdownFilter: { breakdown: '$browser', limit: 25, breakdown_limit: 10 },
            }

            const result = stripUnsupportedQueryFields(input as unknown as InsightQueryNode) as Record<string, any>

            expect(result.breakdownFilter.limit).toBeUndefined()
            expect(result.breakdownFilter.breakdown_limit).toBe(10)
        })
    })
})

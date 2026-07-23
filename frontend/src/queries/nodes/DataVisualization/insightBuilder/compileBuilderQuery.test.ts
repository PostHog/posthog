import { InsightBuilderConfig } from '~/queries/schema/schema-general'

import {
    BuilderCompileError,
    compileBuilderQuery,
    detectSelectAllTarget,
    dimensionExpr,
    filterExpr,
    isCompilableBase,
    measureExpr,
    sanitizeAlias,
} from './compileBuilderQuery'

const config = (overrides: Partial<InsightBuilderConfig>): InsightBuilderConfig => ({
    enabled: true,
    baseQuery: 'SELECT * FROM events',
    rows: [],
    columns: [],
    values: [],
    ...overrides,
})

describe('compileBuilderQuery', () => {
    it('compiles rows + columns + values into a grouped, ordered query', () => {
        const result = compileBuilderQuery(
            config({
                rows: [{ column: 'created_at', dateGrain: 'month' }],
                columns: [{ column: 'plan' }],
                values: [{ column: 'amount', aggregation: 'sum' }],
            })
        )

        expect(result.sql).toEqual(
            [
                'SELECT',
                // Columns (x-axis) first, then Rows (breakdown), then Values
                '    plan AS plan,',
                '    toStartOfMonth(created_at) AS created_at_month,',
                '    sum(amount) AS sum_amount',
                'FROM (',
                'SELECT * FROM events',
                ')',
                'GROUP BY plan, toStartOfMonth(created_at)',
                'ORDER BY plan ASC',
            ].join('\n')
        )
        expect(result.rowAliases).toEqual(['created_at_month'])
        expect(result.columnAliases).toEqual(['plan'])
        expect(result.valueAliases).toEqual(['sum_amount'])
    })

    it('compiles values-only wells without GROUP BY or ORDER BY', () => {
        const result = compileBuilderQuery(config({ values: [{ column: 'amount', aggregation: 'avg' }] }))

        expect(result.sql).not.toContain('GROUP BY')
        expect(result.sql).not.toContain('ORDER BY')
        expect(result.valueAliases).toEqual(['avg_amount'])
    })

    it('orders by the first column dimension (the x-axis)', () => {
        const result = compileBuilderQuery(
            config({
                columns: [{ column: 'plan' }],
                values: [{ column: 'amount', aggregation: 'sum' }],
            })
        )

        expect(result.sql).toContain('ORDER BY plan ASC')
    })

    it('uses the view name as FROM when baseView is set', () => {
        const result = compileBuilderQuery(
            config({
                baseView: 'my_schema.revenue view',
                values: [{ column: 'amount', aggregation: 'sum' }],
            })
        )

        expect(result.sql).toContain('FROM my_schema."revenue view"')
        expect(result.sql).not.toContain('SELECT * FROM events')
    })

    it('strips a trailing semicolon from the base query', () => {
        const result = compileBuilderQuery(
            config({
                baseQuery: 'SELECT * FROM events;',
                values: [{ column: 'amount', aggregation: 'sum' }],
            })
        )

        expect(result.sql).toContain('FROM (\nSELECT * FROM events\n)')
    })

    it('keeps HogQL variable placeholders in the base query intact', () => {
        const result = compileBuilderQuery(
            config({
                baseQuery: 'SELECT * FROM events WHERE properties.plan = {variables.plan_filter}',
                values: [{ column: 'amount', aggregation: 'sum' }],
            })
        )

        expect(result.sql).toContain('{variables.plan_filter}')
    })

    it.each([
        [
            'multi-statement base',
            config({ baseQuery: 'SELECT 1; SELECT 2', values: [{ column: 'a', aggregation: 'sum' }] }),
        ],
        ['empty base', config({ baseQuery: '   ', values: [{ column: 'a', aggregation: 'sum' }] })],
        ['empty wells', config({})],
        ['star with non-count aggregation', config({ values: [{ column: '*', aggregation: 'sum' }] })],
    ])('throws BuilderCompileError for %s', (_name, invalidConfig) => {
        expect(() => compileBuilderQuery(invalidConfig)).toThrow(BuilderCompileError)
    })

    it('groups by expressions rather than aliases so aliases can never shadow source columns', () => {
        const result = compileBuilderQuery(
            config({
                rows: [{ column: 'created_at', dateGrain: 'day' }],
                values: [{ column: 'amount', aggregation: 'sum' }],
            })
        )

        expect(result.sql).toContain('GROUP BY toDate(created_at)')
        expect(result.sql).not.toContain('GROUP BY created_at_day')
    })

    describe('dimensionExpr', () => {
        it.each([
            [{ column: 'ts', dateGrain: 'hour' } as const, 'toStartOfHour(ts)'],
            // Day buckets to a DATE (not a DateTime at midnight) so the axis shows a date, not "00:00"
            [{ column: 'ts', dateGrain: 'day' } as const, 'toDate(ts)'],
            [{ column: 'ts', dateGrain: 'week' } as const, 'toStartOfWeek(ts)'],
            [{ column: 'ts', dateGrain: 'month' } as const, 'toStartOfMonth(ts)'],
            [{ column: 'ts', dateGrain: 'quarter' } as const, 'toStartOfQuarter(ts)'],
            [{ column: 'ts', dateGrain: 'year' } as const, 'toStartOfYear(ts)'],
            [{ column: 'plain' } as const, 'plain'],
            [{ column: 'order value' } as const, '"order value"'],
            [{ column: 'amount', numericBinWidth: 10 } as const, 'floor(amount / 10) * 10'],
            [{ column: 'order value', numericBinWidth: 2.5 } as const, 'floor("order value" / 2.5) * 2.5'],
            // Non-positive bin width is ignored (treated as exact)
            [{ column: 'amount', numericBinWidth: 0 } as const, 'amount'],
            // Date grain wins if both are somehow set
            [{ column: 'ts', dateGrain: 'day', numericBinWidth: 10 } as const, 'toDate(ts)'],
        ])('compiles %o to %s', (dim, expected) => {
            expect(dimensionExpr(dim)).toEqual(expected)
        })
    })

    describe('measureExpr', () => {
        it.each([
            [{ column: 'x', aggregation: 'sum' } as const, 'sum(x)'],
            [{ column: 'x', aggregation: 'avg' } as const, 'avg(x)'],
            [{ column: 'x', aggregation: 'min' } as const, 'min(x)'],
            [{ column: 'x', aggregation: 'max' } as const, 'max(x)'],
            [{ column: 'x', aggregation: 'count' } as const, 'count(x)'],
            [{ column: 'x', aggregation: 'count_distinct' } as const, 'countDistinct(x)'],
            [{ column: 'x', aggregation: 'median' } as const, 'median(x)'],
            [{ column: 'x', aggregation: 'p90' } as const, 'quantile(0.9)(x)'],
            [{ column: 'x', aggregation: 'p95' } as const, 'quantile(0.95)(x)'],
            [{ column: 'x', aggregation: 'p99' } as const, 'quantile(0.99)(x)'],
            [{ column: '*', aggregation: 'count' } as const, 'count()'],
            [{ column: 'col with space', aggregation: 'sum' } as const, 'sum("col with space")'],
            [{ column: 'back`tick', aggregation: 'sum' } as const, 'sum("back`tick")'],
            [{ column: 'has "quote', aggregation: 'sum' } as const, 'sum(`has "quote`)'],
            [{ column: 'both`"kinds', aggregation: 'sum' } as const, 'sum(`both``"kinds`)'],
        ])('compiles %o to %s', (measure, expected) => {
            expect(measureExpr(measure)).toEqual(expected)
        })
    })

    describe('sanitizeAlias', () => {
        it.each([
            ['Order Value', 'order_value'],
            ['  spaced  ', 'spaced'],
            ['9lives', '_9lives'],
            ['__proto__', 'proto'],
            ['%%%', 'field'],
            ['from', 'from_'],
            ['ORDER', 'order_'],
        ])('sanitizes %s to %s', (raw, expected) => {
            expect(sanitizeAlias(raw, new Set())).toEqual(expected)
        })

        it('dedupes collisions with numeric suffixes', () => {
            const taken = new Set<string>()
            expect(sanitizeAlias('amount', taken)).toEqual('amount')
            expect(sanitizeAlias('Amount', taken)).toEqual('amount_2')
            expect(sanitizeAlias('amount!', taken)).toEqual('amount_3')
        })

        it('dedupes across wells when compiling so chart series never collide', () => {
            const result = compileBuilderQuery(
                config({
                    rows: [{ column: 'sum_amount' }],
                    values: [{ column: 'amount', aggregation: 'sum' }],
                })
            )

            expect(result.rowAliases).toEqual(['sum_amount'])
            expect(result.valueAliases).toEqual(['sum_amount_2'])
        })
    })

    describe('filters', () => {
        it('compiles complete filters into a WHERE clause before GROUP BY', () => {
            const result = compileBuilderQuery(
                config({
                    rows: [{ column: 'plan' }],
                    values: [{ column: 'amount', aggregation: 'sum' }],
                    filters: [
                        { column: 'region', operator: 'eq', value: 'EU' },
                        { column: 'amount', operator: 'gt', value: '100' },
                    ],
                })
            )

            expect(result.sql).toContain("WHERE region = 'EU' AND amount > '100'")
            expect(result.sql.indexOf('WHERE')).toBeLessThan(result.sql.indexOf('GROUP BY'))
        })

        it('skips incomplete filters so typing a value never breaks the query', () => {
            const result = compileBuilderQuery(
                config({
                    values: [{ column: 'amount', aggregation: 'sum' }],
                    filters: [
                        { column: 'region', operator: 'eq' },
                        { column: 'region', operator: 'neq', value: '' },
                    ],
                })
            )

            expect(result.sql).not.toContain('WHERE')
        })

        it.each([
            [{ column: 'plan', operator: 'contains', value: '50%_off' } as const, "plan ILIKE '%50\\\\%\\\\_off%'"],
            [{ column: 'plan', operator: 'not_contains', value: 'x' } as const, "plan NOT ILIKE '%x%'"],
            [{ column: 'plan', operator: 'is_set' } as const, 'isNotNull(plan)'],
            [{ column: 'plan', operator: 'is_not_set' } as const, 'isNull(plan)'],
            [{ column: 'note', operator: 'eq', value: "it's" } as const, "note = 'it\\'s'"],
        ])('compiles %o', (filter, expected) => {
            expect(filterExpr(filter)).toEqual(expected)
        })
    })

    describe('detectSelectAllTarget', () => {
        it.each([
            ['SELECT * FROM payments', 'payments'],
            ['select * from payments limit 100', 'payments'],
            ['SELECT * FROM payments LIMIT 100;', 'payments'],
            ['  SELECT  *  FROM  schema.revenue  ', 'schema.revenue'],
            ['SELECT * FROM "my view" LIMIT 100', 'my view'],
            ['SELECT * FROM `back``tick` LIMIT 5', 'back`tick'],
            ['SELECT id FROM payments', null],
            ['SELECT * FROM payments WHERE id > 1', null],
            ['SELECT * FROM (SELECT 1)', null],
            ['SELECT * FROM payments LIMIT 100 OFFSET 5', null],
        ])('detects %s → %s', (base, expected) => {
            expect(detectSelectAllTarget(base)).toEqual(expected)
        })
    })

    describe('isCompilableBase', () => {
        it.each([
            ['SELECT 1', true],
            ['SELECT 1;', true],
            ['SELECT 1; SELECT 2', false],
            ['', false],
            ['   ', false],
        ])('returns %s → %s', (base, expected) => {
            expect(isCompilableBase(base)).toEqual(expected)
        })
    })
})

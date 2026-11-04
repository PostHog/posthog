import { getDotMatrixCellCount, normalizeDotMatrixData } from 'lib/components/DotMatrix/dotMatrixData'

import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { getDotMatrixTileConfig } from './dotMatrixTileConfig'
import { getDotMatrixTilePresentation } from './dotMatrixTilePresentation'
import { createMatrixHogQLQuery } from './dotMatrixTileQuery'
import {
    DEFAULT_MATRIX_QUERY,
    DOT_MATRIX_MAX_COLUMNS,
    DOT_MATRIX_MAX_ROWS,
    DOT_MATRIX_MAX_SERIES,
    getHogQLActivityMatrix,
    inferHogQLMatrixMapping,
    getHogQLLimitNotice,
} from './hogqlActivityMatrix'

describe('HogQL activity matrix', () => {
    it.each([
        [['who', 'period'], { row: 'who', column: 'period' }],
        [
            ['amount', 'week', 'person', 'feature'],
            { row: 'person', column: 'week', series: 'feature', value: 'amount' },
        ],
        [['a', 'b', 'c'], { row: 'a', column: 'b', value: 'c' }],
        [['a', 'b', 'c', 'd'], { row: 'a', column: 'b', series: 'c', value: 'd' }],
    ])('maps result columns by name, then position (%j)', (columns, expected) => {
        expect(
            inferHogQLMatrixMapping(columns as string[], {
                row: 'row',
                column: 'column',
                series: 'series',
                value: 'value',
            })
        ).toEqual(expected)
    })

    it('keeps valid manual mappings when a query runs again', () => {
        const mapping = { row: 'b', column: 'a' }
        expect(inferHogQLMatrixMapping(['a', 'b', 'series'], mapping)).toEqual(mapping)
    })

    it('keeps stable row keys and uses a separate readable label, with an ID fallback', () => {
        const mapping = { row: 'person_id', column: 'week', rowLabel: 'email' }
        const result = getHogQLActivityMatrix(
            {
                columns: ['person_id', 'week', 'email'],
                results: [
                    ['p1', 'w1', 'alex@example.com'],
                    ['p2', 'w1', null],
                ],
            },
            mapping
        )
        expect(result.props?.rows).toEqual([
            { key: 'p1', label: 'alex@example.com' },
            { key: 'p2', label: 'p2' },
        ])
        expect(result.props?.rowHeader?.title).toBe('Email')
        expect(getDotMatrixTileConfig({ source: { kind: 'hogql', query: 'SELECT 1', mapping } }).source).toMatchObject({
            mapping,
        })
    })

    it.each([0, 1])('uses the project week start in the starter SQL (%s)', (weekStartDay) => {
        expect(DEFAULT_MATRIX_QUERY).toContain('toStartOfWeek(timestamp, {week_start_day})')
        expect(
            createMatrixHogQLQuery(DEFAULT_MATRIX_QUERY, {
                accountId: 'a',
                externalId: 'org',
                groupTypeIndex: 0,
                weeks: 8,
                weekStartDay,
            }).values
        ).toMatchObject({ week_start_day: weekStartDay })
    })

    it('maps a renamed value when the row and column aliases stay the same', () => {
        expect(
            inferHogQLMatrixMapping(['row', 'column', 'total'], {
                row: 'row',
                column: 'column',
                series: 'series',
                value: 'value',
            })
        ).toEqual({ row: 'row', column: 'column', value: 'total' })
    })

    it('counts only displayed series when the series limit trims people', () => {
        const { props } = getHogQLActivityMatrix(
            {
                columns: ['r', 'c', 's', 'u'],
                results: Array.from({ length: DOT_MATRIX_MAX_SERIES + 1 }, (_, i) => [
                    'account',
                    'week',
                    `s${i}`,
                    `p${i}`,
                ]),
            },
            { row: 'r', column: 'c', series: 's', user: 'u' }
        )
        const cell = normalizeDotMatrixData(props!).getCell('account', 'week')
        expect(getDotMatrixCellCount(cell, props!)).toBe(DOT_MATRIX_MAX_SERIES)
        expect(getDotMatrixCellCount(cell, { ...props!, selectedSeries: props!.series!.map(({ key }) => key) })).toBe(
            DOT_MATRIX_MAX_SERIES
        )
    })

    it('maps column names independently of their order and sums duplicate cells', () => {
        const result = getHogQLActivityMatrix(
            {
                columns: ['amount', 'week', 'person', 'feature'],
                results: [
                    [0.5, 'w1', 'p1', 'a'],
                    [2, 'w1', 'p1', 'a'],
                    [4, 'w1', 'p1', 'b'],
                ],
            },
            { row: 'person', column: 'week', series: 'feature', value: 'amount' }
        )
        expect(result.error).toBeNull()
        const cell = normalizeDotMatrixData(result.props!).getCell('p1', 'w1')
        expect(getDotMatrixCellCount(cell, { ...result.props, selectedSeries: ['a', 'b'] })).toBe(6.5)
        expect(result.props!.sizeThresholds?.[0]).toBe(1)
    })

    it('counts result rows with one series when optional mappings are absent', () => {
        const result = getHogQLActivityMatrix(
            {
                columns: ['r', 'c'],
                results: [
                    ['person', 'week'],
                    ['person', 'week'],
                ],
            },
            { row: 'r', column: 'c' }
        )
        expect(normalizeDotMatrixData(result.props!).getCell('person', 'week').values).toEqual({ value: 2 })
    })

    it.each([
        { columns: ['r', 'r', 'value'], results: [] },
        { columns: ['r', 'missing', 'value'], results: [] },
        { columns: ['r', 'c', 'value'], results: [[null, 'week', 1]] },
        { columns: ['r', 'c', 'value'], results: [['person', 'week', '2']] },
        { columns: ['r', 'c', 'value'], results: [['person', 'week', -1]] },
        { columns: ['r', 'c', 'value'], results: [['person', 'week', Infinity]] },
    ])('rejects an ambiguous or invalid result (%j)', (response) => {
        expect(getHogQLActivityMatrix(response, { row: 'r', column: 'c', value: 'value' })).toMatchObject({
            props: null,
            error: expect.any(String),
        })
    })

    it('passes account context as query values and scopes the starter filter to the account group', () => {
        const query = createMatrixHogQLQuery('SELECT {account_external_id} FROM events WHERE {filters}', {
            accountId: 'account',
            externalId: "org'quote",
            groupTypeIndex: 2,
            weeks: 8,
        })
        expect(query).toEqual({
            kind: NodeKind.HogQLQuery,
            tags: { productKey: 'customer_analytics', scene: 'CustomerAnalytics' },
            query: 'SELECT {account_external_id} FROM events WHERE {filters}',
            values: { account_id: 'account', account_external_id: "org'quote", week_start_day: 0 },
            filters: {
                dateRange: { date_from: '-7wStart', date_to: null },
                properties: [
                    {
                        type: PropertyFilterType.Event,
                        key: '$group_2',
                        operator: PropertyOperator.Exact,
                        value: ["org'quote"],
                    },
                ],
            },
        })
        expect(() =>
            createMatrixHogQLQuery('SELECT 1 FROM events WHERE {filters}', { accountId: 'account', weeks: 8 })
        ).toThrow('Link this account')
    })

    describe('bounding the axes', () => {
        it('caps distinct axes before normalization allocates their product, and says so', () => {
            const results = Array.from({ length: 2000 }, (_, index) => [`r${index}`, `c${index}`, `s${index}`, 1])
            const result = getHogQLActivityMatrix(
                { columns: ['r', 'c', 's', 'v'], results },
                { row: 'r', column: 'c', series: 's', value: 'v' }
            )

            expect(result.props!.rows).toHaveLength(DOT_MATRIX_MAX_ROWS)
            expect(result.props!.columns).toHaveLength(DOT_MATRIX_MAX_COLUMNS)
            expect(result.props!.series).toHaveLength(DOT_MATRIX_MAX_SERIES)

            const matrix = normalizeDotMatrixData(result.props!)
            const cellCount = [...matrix.cells.values()].reduce((total, cells) => total + cells.size, 0)
            expect(matrix.rows).toHaveLength(DOT_MATRIX_MAX_ROWS)
            expect(matrix.columns).toHaveLength(DOT_MATRIX_MAX_COLUMNS)
            expect(cellCount).toBe(DOT_MATRIX_MAX_ROWS * DOT_MATRIX_MAX_COLUMNS)
            expect(result.notices).toEqual([
                `Showing ${DOT_MATRIX_MAX_ROWS} of 2000 rows, ${DOT_MATRIX_MAX_COLUMNS} of 2000 columns and ${DOT_MATRIX_MAX_SERIES} of 2000 series. Narrow the query to see the rest.`,
            ])
        })

        it('adds no notice when the result fits', () => {
            const result = getHogQLActivityMatrix(
                { columns: ['r', 'c'], results: [['a', 'b']] },
                { row: 'r', column: 'c' }
            )
            expect(result.notices).toEqual([])
        })

        it('passes bound notices through the tile presentation, alongside hasMore', () => {
            const results = Array.from({ length: DOT_MATRIX_MAX_ROWS + 1 }, (_, index) => [`r${index}`, 'c'])
            const presentation = getDotMatrixTilePresentation(
                { kind: 'hogql', query: 'SELECT 1', result: { columns: ['r', 'c'], results, hasMore: true } },
                [],
                { row: 'r', column: 'c' },
                8
            )
            expect(presentation.notices).toEqual([
                `Showing ${DOT_MATRIX_MAX_ROWS} of ${DOT_MATRIX_MAX_ROWS + 1} rows. Narrow the query to see the rest.`,
                'Showing a limited result. Narrow the date range or query to include all activity.',
            ])
        })
    })

    describe('long series values', () => {
        const LONG_A = `${'x'.repeat(200)}a`
        const LONG_B = `${'x'.repeat(200)}b`
        const mapping = { row: 'r', column: 'c', series: 's', value: 'v' }
        const response = {
            columns: ['r', 'c', 's', 'v'],
            results: [
                ['person', 'week', LONG_A, 1],
                ['person', 'week', LONG_B, 2],
                ['person', 'week', 'short', 3],
            ],
        }

        it('encodes keys the saved selection accepts, keeps them distinct and labels the original value', () => {
            const { props } = getHogQLActivityMatrix(response, mapping)
            const [first, second, short] = props!.series!

            expect(first.key).not.toEqual(second.key)
            expect(first.key.length).toBeLessThanOrEqual(128)
            expect(second.key.length).toBeLessThanOrEqual(128)
            expect(first.label?.startsWith('xxx')).toBe(true)
            expect(short).toEqual({ key: 'short' })
            expect(normalizeDotMatrixData(props!).getCell('person', 'week').values).toEqual({
                [first.key]: 1,
                [second.key]: 2,
                short: 3,
            })
            expect(getDotMatrixTileConfig({ selectedSeries: [first.key, second.key] }).selectedSeries).toEqual([
                first.key,
                second.key,
            ])
        })

        it('gives the same value the same key on every run, so a saved selection still applies', () => {
            const firstRun = getHogQLActivityMatrix(response, mapping).props!.series!
            const secondRun = getHogQLActivityMatrix({ ...response, results: [...response.results].reverse() }, mapping)
                .props!.series!
            expect(secondRun.map(({ key }) => key).sort()).toEqual(firstRun.map(({ key }) => key).sort())
        })
    })

    describe('column order', () => {
        const columnsOf = (values: unknown[]): string[] =>
            getHogQLActivityMatrix(
                { columns: ['r', 'c'], results: values.map((value) => ['person', value]) },
                { row: 'r', column: 'c' }
            ).props!.columns!.map(({ key }) => key)

        it.each([
            [
                'newest-first dates',
                ['2026-11-01', '2026-10-25', '2026-09-13'],
                ['2026-09-13', '2026-10-25', '2026-11-01'],
            ],
            ['unordered dates', ['2026-09-27', '2026-09-20', '2026-10-04'], ['2026-09-20', '2026-09-27', '2026-10-04']],
            [
                'datetimes',
                ['2026-10-04T10:00:00Z', '2026-10-04 09:00:00', '2026-10-03T23:00:00+00:00'],
                ['2026-10-03T23:00:00+00:00', '2026-10-04 09:00:00', '2026-10-04T10:00:00Z'],
            ],
            ['months', ['2026-10', '2026-09'], ['2026-09', '2026-10']],
            ['numbers', [10, 9, 100], ['9', '10', '100']],
            ['numeric text', ['10', '9', '100.5'], ['9', '10', '100.5']],
        ])('sorts %s ascending, left to right', (_, values, expected) => {
            expect(columnsOf(values)).toEqual(expected)
        })

        it.each([
            ['text labels', ['Beta', 'Alpha', 'Gamma']],
            ['a mix of dates and text', ['2026-10-04', 'Total', '2026-09-27']],
            ['an impossible date', ['2026-13-45', '2026-01-01']],
        ])('keeps the query order for %s', (_, values) => {
            expect(columnsOf(values)).toEqual(values)
        })

        it('keeps the latest dated columns when it has to drop some', () => {
            const dates = Array.from({ length: DOT_MATRIX_MAX_COLUMNS + 2 }, (_, index) =>
                new Date(Date.UTC(2024, 0, 1 + index)).toISOString().slice(0, 10)
            ).reverse()
            const shown = columnsOf(dates)
            expect(shown).toHaveLength(DOT_MATRIX_MAX_COLUMNS)
            expect(shown[shown.length - 1]).toBe(dates[0])
            expect(shown).not.toContain('2024-01-01')
        })

        it('fetches newest first in the default query, so a LIMIT drops the oldest weeks', () => {
            expect(DEFAULT_MATRIX_QUERY).toContain('ORDER BY column DESC, row, series')
        })
    })

    describe('detecting a result cut off by LIMIT', () => {
        const rows = (count: number): unknown[][] => Array.from({ length: count }, () => ['a'])
        const notice = (results: unknown[][], hogql?: string, query = 'SELECT 1'): string | null =>
            getHogQLLimitNotice({ columns: ['r'], results, hogql }, query)

        it('warns when the row count reaches the LIMIT the server ran', () => {
            expect(notice(rows(5), 'SELECT\n    event\nFROM\n    events\nLIMIT 5')).toBe(
                'The query returned exactly its LIMIT of 5 rows, so some data may be missing. Raise the LIMIT to check.'
            )
        })

        it('stays quiet when fewer rows came back than the LIMIT', () => {
            expect(notice(rows(4), 'SELECT event FROM events LIMIT 5')).toBeNull()
        })

        it('falls back to the query text when the response has no printed query', () => {
            expect(notice(rows(3), undefined, 'select event from events limit 3')).toContain('LIMIT of 3')
        })

        it('uses the limit the server capped to, not the one the user asked for', () => {
            expect(
                notice(rows(50), 'SELECT event FROM events LIMIT 50', 'SELECT event FROM events LIMIT 99999')
            ).toContain('LIMIT of 50')
        })

        it.each([
            ['a subquery limit', 'SELECT a FROM (SELECT a FROM events LIMIT 2)'],
            ['LIMIT n BY', 'SELECT a FROM events LIMIT 2 BY a'],
            ['a string', "SELECT 'LIMIT 2' AS a FROM events"],
            ['a comment', 'SELECT a FROM events -- LIMIT 2'],
            ['a block comment', 'SELECT a FROM events /* LIMIT 2 */'],
            ['a column name', 'SELECT limit_2 FROM events'],
        ])('ignores %s', (_, hogql) => {
            expect(notice(rows(2), hogql)).toBeNull()
        })

        it('reads the outer LIMIT past a LIMIT BY and with an OFFSET', () => {
            expect(notice(rows(2), 'SELECT a FROM events LIMIT 1 BY a LIMIT 2 OFFSET 1')).toContain('LIMIT of 2')
        })

        it('takes the count from LIMIT offset, count', () => {
            expect(notice(rows(2), 'SELECT a FROM events LIMIT 7, 2')).toContain('LIMIT of 2')
        })

        it('shows through the tile presentation, and leaves hasMore its own message', () => {
            const present = (hasMore: boolean): string[] =>
                getDotMatrixTilePresentation(
                    {
                        kind: 'hogql',
                        query: 'SELECT r, c FROM events LIMIT 1',
                        result: { columns: ['r', 'c'], results: [['a', 'b']], hasMore },
                    },
                    [],
                    { row: 'r', column: 'c' },
                    8
                ).notices
            expect(present(false)[0]).toContain('LIMIT of 1')
            expect(present(true)).toEqual([
                'Showing a limited result. Narrow the date range or query to include all activity.',
            ])
        })
    })

    describe('counting people across series', () => {
        const RESULTS = [
            ['all', 'w1', 'a', 'p1'],
            ['all', 'w1', 'a', 'p1'],
            ['all', 'w1', 'a', 'p2'],
            ['all', 'w1', 'b', 'p1'],
            ['all', 'w1', 'c', 'p3'],
        ]
        const USER_MAPPING = { row: 'r', column: 'c', series: 's', user: 'u' }

        it('counts each person once across selected series when a user column is mapped', () => {
            const { props } = getHogQLActivityMatrix({ columns: ['r', 'c', 's', 'u'], results: RESULTS }, USER_MAPPING)
            const cell = normalizeDotMatrixData(props!).getCell('all', 'w1')

            expect(cell.values).toEqual({ a: 2, b: 1, c: 1 })
            expect(getDotMatrixCellCount(cell, { ...props, selectedSeries: ['a', 'b'] })).toBe(2)
            expect(getDotMatrixCellCount(cell, { ...props, selectedSeries: ['a', 'b', 'c'] })).toBe(3)
            expect(getDotMatrixCellCount(cell, { ...props, selectedSeries: ['b'] })).toBe(1)
            expect(getDotMatrixCellCount(cell, { ...props })).toBe(3)
            expect(props!.legend).toMatchObject({ valueLabel: 'People', countLabel: 'People' })
            expect((props!.legend as any).selectionLabel(2, 'count')).toBe('People in 2 selected series')
            expect((props!.legend as any).selectionLabel(2, 'dots')).toBe('Showing 2 series')
        })

        it('keeps the value column for dots, but only counts people with a positive value', () => {
            const { props } = getHogQLActivityMatrix(
                {
                    columns: ['r', 'c', 's', 'u', 'v'],
                    results: [
                        ['all', 'w1', 'a', 'p1', 5],
                        ['all', 'w1', 'b', 'p1', 7],
                        ['all', 'w1', 'b', 'p2', 0],
                    ],
                },
                { ...USER_MAPPING, value: 'v' }
            )
            const cell = normalizeDotMatrixData(props!).getCell('all', 'w1')

            expect(cell.values).toEqual({ a: 5, b: 7 })
            expect(getDotMatrixCellCount(cell, { ...props, selectedSeries: ['a', 'b'] })).toBe(1)
            expect(props!.legend).toMatchObject({ valueLabel: 'v' })
        })

        it('sums a generic value and never calls the result people without a user column', () => {
            const { props } = getHogQLActivityMatrix(
                {
                    columns: ['r', 'c', 's', 'v'],
                    results: [
                        ['all', 'w1', 'a', 2],
                        ['all', 'w1', 'b', 1],
                    ],
                },
                { row: 'r', column: 'c', series: 's', value: 'v' }
            )
            const cell = normalizeDotMatrixData(props!).getCell('all', 'w1')
            const label = (props!.legend as any).selectionLabel(2, 'count')

            expect(getDotMatrixCellCount(cell, { ...props, selectedSeries: ['a', 'b'] })).toBe(3)
            expect(label).toBe('Sum of v across 2 series. Map a user column to count each person once.')
            expect(`${label} ${(props!.legend as any).countLabel}`).not.toMatch(/\b(people|users?) (in|selected)/i)
            expect(props!.legend).toMatchObject({ countLabel: 'Sum of v' })
            expect((props!.legend as any).selectionLabel(2, 'dots')).toBe('Showing 2 series')
        })

        it('reports a mapped user column missing from the result', () => {
            expect(
                getHogQLActivityMatrix({ columns: ['r', 'c'], results: [] }, { row: 'r', column: 'c', user: 'gone' })
                    .error
            ).toBe('A mapped column is missing from the result. Update the mapping.')
        })
    })

    describe('rows with missing values', () => {
        const mapping = { row: 'r', column: 'c', series: 's', value: 'v' }

        it('skips only the rows with a missing or invalid value, and says how many', () => {
            const result = getHogQLActivityMatrix(
                {
                    columns: ['r', 'c', 's', 'v'],
                    results: [
                        ['person', 'week', 'a', 1],
                        [null, 'week', 'a', 1],
                        ['person', null, 'a', 1],
                        ['person', 'week', null, 1],
                        ['person', 'week', 'b', null],
                        ['', 'week', 'a', 1],
                        ['person', 'week', 'c', -1],
                    ],
                },
                mapping
            )
            expect(result.error).toBeNull()
            expect(result.props!.rows).toEqual([{ key: 'person' }])
            expect(result.props!.series).toEqual([{ key: 'a' }])
            expect(result.notices).toEqual(['Skipped 6 result rows with a missing or invalid value.'])
        })

        it('uses the singular for one skipped row, and keeps the query saveable', () => {
            const result = getHogQLActivityMatrix(
                {
                    columns: ['r', 'c', 's', 'v'],
                    results: [
                        ['person', 'week', 'a', 1],
                        [null, 'week', 'a', 1],
                    ],
                },
                mapping
            )
            expect(result.error).toBeNull()
            expect(result.notices).toEqual(['Skipped 1 result row with a missing or invalid value.'])
        })

        it('skips a row with no user when a user column is mapped', () => {
            const result = getHogQLActivityMatrix(
                {
                    columns: ['r', 'c', 'u'],
                    results: [
                        ['person', 'week', 'p1'],
                        ['person', 'week', null],
                    ],
                },
                { row: 'r', column: 'c', user: 'u' }
            )
            expect(result.notices).toEqual(['Skipped 1 result row with a missing or invalid value.'])
        })

        it('reports an error when no row is usable, since the mapping is likely wrong', () => {
            const result = getHogQLActivityMatrix(
                { columns: ['r', 'c', 's', 'v'], results: [[null, 'week', 'a', 1]] },
                mapping
            )
            expect(result.props).toBeNull()
            expect(result.error).toEqual(expect.any(String))
        })
    })
})

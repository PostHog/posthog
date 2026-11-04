import { getDotMatrixCellCount, normalizeDotMatrixData } from 'lib/components/DotMatrix/dotMatrixData'

import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { getDotMatrixTilePresentation } from './dotMatrixTilePresentation'
import { createMatrixHogQLQuery } from './dotMatrixTileQuery'
import {
    DOT_MATRIX_MAX_COLUMNS,
    DOT_MATRIX_MAX_ROWS,
    DOT_MATRIX_MAX_SERIES,
    getHogQLActivityMatrix,
} from './hogqlActivityMatrix'

describe('HogQL activity matrix', () => {
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
            query: 'SELECT {account_external_id} FROM events WHERE {filters}',
            values: { account_id: 'account', account_external_id: "org'quote" },
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
})

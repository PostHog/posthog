import { getDotMatrixCellCount, normalizeDotMatrixData } from 'lib/components/DotMatrix/dotMatrixData'

import { NodeKind } from '~/queries/schema/schema-general'
import { PropertyFilterType, PropertyOperator } from '~/types'

import { createMatrixHogQLQuery } from './dotMatrixTileQuery'
import { getHogQLActivityMatrix } from './hogqlActivityMatrix'

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
})

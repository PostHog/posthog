import { buildPivotData, pivotRowKey } from './pivotTableUtils'

const columnIndexByName = { region: 0, plan: 1, sum_amount: 2, count_star: 3 }

describe('buildPivotData', () => {
    it('builds a rows × columns matrix with one cell entry per value alias', () => {
        const rows = [
            ['EU', 'free', 10, 100],
            ['EU', 'paid', 20, 200],
            ['US', 'free', 30, 300],
        ]

        const data = buildPivotData(rows, columnIndexByName, {
            rowAliases: ['region'],
            columnAliases: ['plan'],
            valueAliases: ['sum_amount', 'count_star'],
        })

        expect(data.rowKeys).toEqual([['EU'], ['US']])
        expect(data.columnKeys).toEqual(['free', 'paid'])
        expect(data.cells[pivotRowKey(['EU'])]['free']).toEqual([10, 100])
        expect(data.cells[pivotRowKey(['EU'])]['paid']).toEqual([20, 200])
        expect(data.cells[pivotRowKey(['US'])]['free']).toEqual([30, 300])
        expect(data.cells[pivotRowKey(['US'])]['paid']).toBeUndefined()
        expect(data.duplicateCount).toEqual(0)
    })

    it('supports multiple row dimensions and no column dimensions', () => {
        const rows = [
            ['EU', 'free', 10, 100],
            ['EU', 'paid', 20, 200],
        ]

        const data = buildPivotData(rows, columnIndexByName, {
            rowAliases: ['region', 'plan'],
            columnAliases: [],
            valueAliases: ['sum_amount'],
        })

        expect(data.rowKeys).toEqual([
            ['EU', 'free'],
            ['EU', 'paid'],
        ])
        expect(data.columnKeys).toEqual([''])
        expect(data.cells[pivotRowKey(['EU', 'free'])]['']).toEqual([10])
    })

    it('does not collide row tuples whose joined labels overlap', () => {
        const rows = [
            ['a b', 'c', 1, 1],
            ['a', 'b c', 2, 2],
        ]

        const data = buildPivotData(rows, columnIndexByName, {
            rowAliases: ['region', 'plan'],
            columnAliases: [],
            valueAliases: ['sum_amount'],
        })

        expect(data.rowKeys).toHaveLength(2)
        expect(data.cells[pivotRowKey(['a b', 'c'])]['']).toEqual([1])
        expect(data.cells[pivotRowKey(['a', 'b c'])]['']).toEqual([2])
    })

    it('labels null dimension values and counts duplicate combinations (last value wins)', () => {
        const rows = [
            [null, 'free', 1, 1],
            [null, 'free', 5, 5],
        ]

        const data = buildPivotData(rows, columnIndexByName, {
            rowAliases: ['region'],
            columnAliases: ['plan'],
            valueAliases: ['sum_amount'],
        })

        expect(data.rowKeys).toEqual([['(null)']])
        expect(data.duplicateCount).toEqual(1)
        expect(data.cells[pivotRowKey(['(null)'])]['free']).toEqual([5])
    })

    it('does not pollute Object.prototype via __proto__ labels', () => {
        const rows = [['__proto__', 'polluted', 1, 1]]

        const data = buildPivotData(rows, columnIndexByName, {
            rowAliases: ['region'],
            columnAliases: ['plan'],
            valueAliases: ['sum_amount'],
        })

        expect(data.cells[pivotRowKey(['__proto__'])]['polluted']).toEqual([1])
        expect(({} as any).polluted).toBeUndefined()
        expect(Object.prototype).not.toHaveProperty('polluted')
    })

    it('returns empty data when an alias is missing from the response columns', () => {
        const data = buildPivotData([['EU', 'free', 1, 1]], columnIndexByName, {
            rowAliases: ['missing'],
            columnAliases: [],
            valueAliases: ['sum_amount'],
        })

        expect(data.rowKeys).toEqual([])
        expect(data.columnKeys).toEqual([])
    })
})

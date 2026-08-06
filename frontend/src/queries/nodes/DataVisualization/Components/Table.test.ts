import { TableDataCell } from '../dataVisualizationLogic'
import { ColumnScalar } from '../types'
import { compareTableCells } from './Table'

function cell(value: string | number | boolean | Date | null, type: ColumnScalar = 'STRING'): TableDataCell<any> {
    return { value, formattedValue: value === null ? null : String(value), type }
}

describe('compareTableCells', () => {
    it.each([
        ['both null', cell(null), cell(null), 0],
        ['a null sorts after b (to bottom of ascending)', cell(null), cell(1, 'INTEGER'), 1],
        ['b null sorts after a (to bottom of ascending)', cell(1, 'INTEGER'), cell(null), -1],
        ['numbers compare numerically, not lexically', cell(2, 'INTEGER'), cell(10, 'INTEGER'), -1],
        ['equal numbers', cell(5, 'INTEGER'), cell(5, 'INTEGER'), 0],
        ['numeric strings use numeric-aware compare', cell('2'), cell('10'), -1],
        ['plain strings compare lexically', cell('apple'), cell('banana'), -1],
        [
            'datetime columns compare chronologically across formats',
            cell('2024-01-01T00:00:00Z', 'DATETIME'),
            cell('2024-12-31', 'DATE'),
            -1,
        ],
        ['unparseable date falls back to string compare', cell('not-a-date', 'DATETIME'), cell('zzz', 'DATETIME'), -1],
        ['undefined cells are treated as null', undefined, cell(1, 'INTEGER'), 1],
    ])('%s', (_label, a, b, expected) => {
        expect(
            Math.sign(compareTableCells(a as TableDataCell<any> | undefined, b as TableDataCell<any> | undefined))
        ).toBe(expected)
    })
})

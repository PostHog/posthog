import { TableDataCell } from '../dataVisualizationLogic'
import { ColumnScalar } from '../types'
import { compareTableCells, isCopyableCellText } from './Table'

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

describe('isCopyableCellText', () => {
    it.each([
        ['git sha string', cell('a1b2c3d'), true],
        ['cuid string', cell('cl9j8k2z00000356xqk9d4hna'), true],
        ['plain number', cell(18.2, 'FLOAT'), true],
        ['boolean', cell(true, 'BOOLEAN'), true],
        // DATE/DATETIME cells render via TZLabel, which has its own tooltip/interaction
        ['date column', cell('2024-01-01', 'DATE'), false],
        ['datetime column', cell('2024-01-01T00:00:00Z', 'DATETIME'), false],
        // TUPLE/ARRAY cells render via JSONCell, which has its own expand/collapse interaction
        ['tuple column', cell('(1, 2)', 'TUPLE'), false],
        ['array column', cell('[1, 2]', 'ARRAY'), false],
        // A STRING column can still hold an ISO datetime or JSON-shaped value rendered specially
        ['ISO datetime string in a STRING column', cell('2024-01-01T00:00:00Z'), false],
        ['JSON object string in a STRING column', cell('{"a": 1}'), false],
        ['JSON array string in a STRING column', cell('[1, 2]'), false],
        // Property() linkifies external URLs, so don't layer click-to-copy on top of the link
        ['external URL string', cell('https://example.com'), false],
    ])('%s', (_label, c, expected) => {
        const cellTitle = c.formattedValue as string
        expect(isCopyableCellText(c, cellTitle)).toBe(expected)
    })
})

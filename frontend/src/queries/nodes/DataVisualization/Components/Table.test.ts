import { TableDataCell } from '../dataVisualizationLogic'
import { ColumnScalar } from '../types'
import { MAX_COLUMN_WIDTH, MIN_COLUMN_WIDTH, compareTableCells, estimateColumnWidths } from './Table'

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

describe('estimateColumnWidths', () => {
    const widthsFor = (titles: string[], rows: (string | number | null)[][]): number[] =>
        estimateColumnWidths(titles, rows.length, (rowIndex, columnIndex) => cell(rows[rowIndex][columnIndex]))

    it('keeps short columns narrow and widens columns with longer values', () => {
        const [period, mrr, label] = widthsFor(
            ['period', 'mrr', 'label'],
            [
                ['2026-11', '$8,565,043', 'A much longer description for this row'],
                ['2026-10', '$7,973,096', 'short'],
            ]
        )

        expect(period).toBeLessThan(150)
        expect(mrr).toBeLessThan(150)
        expect(label).toBeGreaterThan(mrr)
        expect(label).toBeLessThanOrEqual(MAX_COLUMN_WIDTH)
    })

    it('stays inside the width bounds for empty and very long content', () => {
        const [empty, long] = widthsFor(['a', 'b'], [[null, 'x'.repeat(1000)]])

        expect(empty).toBeGreaterThanOrEqual(MIN_COLUMN_WIDTH)
        expect(empty).toBeLessThan(100)
        expect(long).toBe(MAX_COLUMN_WIDTH)
    })

    it('fits the longest header segment, because headers wrap at underscores', () => {
        const [underscored, unbroken] = widthsFor(
            ['a_b_c_d_e_f_g_h_i_j_k_l_m_n', 'abcdefghijklmnopqrstuvwxyz'],
            [[1, 1]]
        )

        expect(underscored).toBeLessThan(unbroken)
    })

    it('includes values found late in the result', () => {
        const rows = Array.from({ length: 1000 }, (_, index) => [index % 100 === 99 ? 'x'.repeat(30) : 'x'])
        const getCell = jest.fn((rowIndex: number, columnIndex: number) => cell(rows[rowIndex][columnIndex]))

        const [width] = estimateColumnWidths(['value'], rows.length, getCell)

        expect(width).toBeGreaterThan(200)
        expect(getCell.mock.calls.length).toBeLessThanOrEqual(1000)
    })

    it('keeps the sampled cells within the budget for very wide tables', () => {
        const columnCount = 10_001
        const titles = Array.from({ length: columnCount }, (_, index) => `row_${index}`)
        const getCell = jest.fn((_rowIndex: number, columnIndex: number) =>
            cell(columnIndex === 0 ? 'field_name' : 'x'.repeat(20))
        )

        const widths = estimateColumnWidths(titles, 10, getCell)

        expect(getCell.mock.calls.length).toBeLessThanOrEqual(5000)
        expect(widths).toHaveLength(columnCount)
        // Unsampled columns reuse the typical sampled width
        expect(widths[1]).toBe(widths[columnCount - 2])
        expect(widths[1]).toBeGreaterThan(150)
    })

    it('sizes HogQLX links by their visible text', () => {
        const link = (text: string): TableDataCell<any> => {
            const value = ['__hx_tag', 'a', 'href', `https://example.com/${'x'.repeat(100)}`, 'children', [text]]
            return { value, formattedValue: value, type: 'STRING' }
        }
        const getCell = (_rowIndex: number, columnIndex: number): TableDataCell<any> =>
            columnIndex === 0 ? link('2026-11') : cell('2026-11')

        const [linkWidth, textWidth] = estimateColumnWidths(['period', 'period'], 3, getCell)

        expect(linkWidth).toBeLessThan(MAX_COLUMN_WIDTH)
        expect(linkWidth).toBe(textWidth)
    })

    it.each([
        ['a sparkline with data', ['__hx_tag', 'Sparkline', 'data', [1, 2, 3]]],
        ['a sparkline that takes its data from children', ['__hx_tag', 'Sparkline', 'children', [1, 2, 3, 4, 5]]],
        ['a recording button', ['__hx_tag', 'RecordingButton', 'sessionId', 'abc']],
    ])('keeps the widest width for %s', (_, value) => {
        const [width] = estimateColumnWidths(['trend'], 1, () => ({ value, formattedValue: value, type: 'STRING' }))

        expect(width).toBe(MAX_COLUMN_WIDTH)
    })

    it('sizes a HogQLX link without children by its href', () => {
        const link = (href: string): TableDataCell<any> => {
            const value = ['__hx_tag', 'a', 'href', href]
            return { value, formattedValue: value, type: 'STRING' }
        }

        const [short] = estimateColumnWidths(['url'], 1, () => link('/a'))
        const [long] = estimateColumnWidths(['url'], 1, () => link(`/${'x'.repeat(30)}`))

        expect(short).toBeLessThan(long)
    })
})

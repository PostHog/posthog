import { getDotMatrixCellCount, normalizeDotMatrixData } from 'lib/components/DotMatrix/dotMatrixData'

import { getBookActivityMatrixProps } from './bookActivityMatrix'
import { BOOK_ACTIVITY_MATRIX_MOCK } from './bookActivityMatrixMock'

describe('bookActivityMatrix', () => {
    it('uses the five and ten user ring thresholds for product usage', () => {
        expect(getBookActivityMatrixProps(BOOK_ACTIVITY_MATRIX_MOCK, []).sizeThresholds).toEqual([1, 5, 10])
    })

    it('uses plural product labels for multi-selection', () => {
        const props = getBookActivityMatrixProps(BOOK_ACTIVITY_MATRIX_MOCK, ['pa', 'replay'])
        expect(props.legend && props.legend.selectionLabel?.(2, 'dots')).toBe('Showing 2 products')
        expect(props.legend && props.legend.selectionLabel?.(1, 'dots')).toBe('Showing 1 product')
    })

    it('counts overlapping product users once using the response series order', () => {
        const response = {
            ...BOOK_ACTIVITY_MATRIX_MOCK,
            series: [
                { key: 'replay', label: 'Replay' },
                { key: 'pa', label: 'Analytics' },
            ],
            data: [
                { row: 'account', column: 'week', series: 'replay', users: 7 },
                { row: 'account', column: 'week', series: 'pa', users: 8 },
            ],
            combinations: [
                { row: 'account', column: 'week', mask: 1, users: 2 },
                { row: 'account', column: 'week', mask: 2, users: 3 },
                { row: 'account', column: 'week', mask: 3, users: 5 },
            ],
        }
        const props = getBookActivityMatrixProps(response, ['pa', 'replay'])
        const cell = normalizeDotMatrixData({ ...props, rows: undefined, columns: undefined }).getCell(
            'account',
            'week'
        )
        expect(getDotMatrixCellCount(cell, { ...props, selectedSeries: ['pa', 'replay'] })).toBe(10)
        expect(getDotMatrixCellCount(cell, { ...props, selectedSeries: ['pa'] })).toBe(8)
        expect(getDotMatrixCellCount(cell, props)).toBe(2)
        expect(props.legend).toMatchObject({ countLabel: 'Users of any of these 2 products' })
    })
})

import { normalizeDotMatrixData } from 'lib/components/DotMatrix/dotMatrixData'

import { getAccountProductUsageProps } from './accountProductUsage'
import { BOOK_ACTIVITY_MATRIX_MOCK } from './bookActivityMatrixMock'

describe('accountProductUsage', () => {
    it('keeps product rows separate and counts distinct active products in the summary', () => {
        const result = {
            ...BOOK_ACTIVITY_MATRIX_MOCK,
            data: [
                { row: 'one', column: '2026-11-02', series: 'pa', users: 10 },
                { row: 'one', column: '2026-11-02', series: 'replay', users: 7 },
                { row: 'two', column: '2026-11-02', series: 'web', users: 20 },
            ],
            columns: [{ key: '2026-11-02', partial: false }],
        }
        const props = getAccountProductUsageProps(result, 'one', 'role')
        const matrix = normalizeDotMatrixData(props)
        expect(matrix.getCell('summary', '2026-11-02').values).toEqual({ summary: 2 })
        const replay = props.rows.find((row) => row.productKey === 'replay')!
        expect(matrix.getCell(replay.key, '2026-11-02').values).toEqual({ replay: 7 })
        expect(props.rows.filter(({ kind }) => kind === 'product')).toHaveLength(2)
        expect(props.rows.filter(({ kind }) => kind === 'group')).toHaveLength(1)
        expect(props.rows.find(({ productKey }) => productKey === 'web')).toBeUndefined()
    })

    it('repeats a product in each use case with the same weekly count', () => {
        const props = getAccountProductUsageProps(
            BOOK_ACTIVITY_MATRIX_MOCK,
            BOOK_ACTIVITY_MATRIX_MOCK.rows[0].key,
            'usecase'
        )
        const replay = props.rows.filter((row) => row.productKey === 'replay')
        expect(replay).toHaveLength(2)
        const matrix = normalizeDotMatrixData(props)
        const column = props.columns![0].key
        expect(matrix.getCell(replay[0].key, column).values).toEqual(matrix.getCell(replay[1].key, column).values)
    })
})

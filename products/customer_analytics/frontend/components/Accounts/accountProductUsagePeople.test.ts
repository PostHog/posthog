import type { BookActivityPerson } from '~/queries/schema/schema-general'

import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { getAccountProductUsagePeopleCell, getLatestProductUsageColumn } from './accountProductUsagePeopleData'

it('shows only the latest period top users with exact count, excluding other periods, products and accounts', () => {
    const result = {
        ...BOOK_ACTIVITY_MATRIX_MOCK,
        columns: [
            { key: '2026-11-02', partial: true },
            { key: '2026-10-26', partial: false },
        ],
        data: [{ row: 'one', column: '2026-11-02', series: 'pa', users: 12 }],
    }
    const people = [
        { row: 'one', column: '2026-10-26', series: 'pa', personId: 'old', rank: 1 },
        { row: 'two', column: '2026-11-02', series: 'pa', personId: 'other-account', rank: 1 },
        { row: 'one', column: '2026-11-02', series: 'replay', personId: 'other-product', rank: 1 },
        { row: 'one', column: '2026-11-02', series: 'pa', personId: 'second', rank: 2 },
        { row: 'one', column: '2026-11-02', series: 'pa', personId: 'first', rank: 1 },
    ] as BookActivityPerson[]
    const column = getLatestProductUsageColumn(result)
    const cell = getAccountProductUsagePeopleCell(result, 'one', people, 'pa', column)
    expect(column).toBe('2026-11-02')
    expect(cell.people.map(({ personId }) => personId)).toEqual(['first', 'second'])
    expect(cell.total).toBe(12)
})

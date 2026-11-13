import { BOOK_ACTIVITY_MATRIX_MOCK } from '../../__mocks__/bookActivityMatrixMock'
import { getProductUsageFirstSeries, getProductUsageGrouping } from '../ProductActivity/productUsagePresentation'

describe('productUsagePresentation', () => {
    it('preserves the canonical role rows and includes products without a role', () => {
        const { series, groups, columnsPerGroup } = getProductUsageGrouping(
            BOOK_ACTIVITY_MATRIX_MOCK.series,
            BOOK_ACTIVITY_MATRIX_MOCK.groupings,
            'role'
        )
        expect(columnsPerGroup).toBe(6)
        expect(groups.map(({ items }) => items?.length)).toEqual([6, 6, 6, 3])
        expect(new Set(groups.flatMap(({ items }) => items))).toHaveProperty('size', 21)
        expect(series.filter(({ group }) => group === 'product_cs').map(({ color }) => color)).toEqual(
            Array(6).fill(groups[0].color)
        )
    })

    it('keeps products in every use case and assigns each product its own color', () => {
        const { series, groups, columnsPerGroup } = getProductUsageGrouping(
            BOOK_ACTIVITY_MATRIX_MOCK.series,
            BOOK_ACTIVITY_MATRIX_MOCK.groupings,
            'usecase'
        )
        expect(columnsPerGroup).toBe(5)
        expect(groups.filter(({ items }) => items?.includes('replay'))).toHaveLength(2)
        expect(new Set(series.map(({ color }) => color)).size).toBe(series.length)
    })

    it.each(['day', 'week', 'month'] as const)('puts first use in its %s bucket only', (interval) => {
        const firstUse = [
            { row: 'one', series: 'a', date: '2026-11-02' },
            { row: 'one', series: 'old', date: '2026-11-01' },
            { row: 'two', series: 'other', date: '2026-11-02' },
        ]
        expect(getProductUsageFirstSeries(firstUse, 'one', '2026-11-02', interval)).toEqual(['a'])
    })
})

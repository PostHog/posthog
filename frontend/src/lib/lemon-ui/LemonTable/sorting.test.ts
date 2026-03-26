import { getNextSorting, Sorting } from './sorting'

describe('getNextSorting', () => {
    describe.each([
        {
            defaultOrder: undefined,
            label: 'default (ascending)',
            firstOrder: 1,
            secondOrder: -1,
        },
        {
            defaultOrder: 1 as const,
            label: 'explicit ascending',
            firstOrder: 1,
            secondOrder: -1,
        },
        {
            defaultOrder: -1 as const,
            label: 'descending',
            firstOrder: -1,
            secondOrder: 1,
        },
    ])('with $label defaultOrder', ({ defaultOrder, firstOrder, secondOrder }) => {
        it.each([
            {
                scenario: 'no current sorting',
                currentSorting: null,
            },
            {
                scenario: 'different column sorted',
                currentSorting: { columnKey: 'other', order: 1 as const },
            },
        ])('returns defaultOrder when $scenario', ({ currentSorting }) => {
            const result = getNextSorting(currentSorting, 'col', false, defaultOrder)
            expect(result).toEqual({ columnKey: 'col', order: firstOrder })
        })

        it('flips to opposite order on second click', () => {
            const current: Sorting = { columnKey: 'col', order: firstOrder as 1 | -1 }
            const result = getNextSorting(current, 'col', false, defaultOrder)
            expect(result).toEqual({ columnKey: 'col', order: secondOrder })
        })

        it('returns null (cancels sorting) on third click', () => {
            const current: Sorting = { columnKey: 'col', order: secondOrder as 1 | -1 }
            const result = getNextSorting(current, 'col', false, defaultOrder)
            expect(result).toBeNull()
        })

        it('loops back to defaultOrder instead of cancelling when disableSortingCancellation is true', () => {
            const current: Sorting = { columnKey: 'col', order: secondOrder as 1 | -1 }
            const result = getNextSorting(current, 'col', true, defaultOrder)
            expect(result).toEqual({ columnKey: 'col', order: firstOrder })
        })
    })
})

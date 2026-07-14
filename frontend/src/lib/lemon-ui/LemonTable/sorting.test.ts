import { compareWithSortings, getNextSorting, getNextSortings, Sorting } from './sorting'

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

describe('multi-column sorting', () => {
    it('keeps existing sort priority when adding, changing, and removing columns', () => {
        const initial: Sorting[] = [{ columnKey: 'runs', order: -1 }]

        const withDuration = getNextSortings(initial, 'duration', false, -1)
        expect(withDuration).toEqual([
            { columnKey: 'runs', order: -1 },
            { columnKey: 'duration', order: -1 },
        ])

        const durationAscending = getNextSortings(withDuration, 'duration', false, -1)
        expect(durationAscending).toEqual([
            { columnKey: 'runs', order: -1 },
            { columnKey: 'duration', order: 1 },
        ])

        expect(getNextSortings(durationAscending, 'duration', false, -1)).toEqual([{ columnKey: 'runs', order: -1 }])
    })

    it('uses later columns to break ties in earlier columns', () => {
        const rows = [
            { name: 'fast-common', runs: 10, duration: 5 },
            { name: 'slow-common', runs: 10, duration: 20 },
            { name: 'slow-rare', runs: 2, duration: 30 },
        ]
        const comparators = {
            runs: (a: (typeof rows)[number], b: (typeof rows)[number]) => a.runs - b.runs,
            duration: (a: (typeof rows)[number], b: (typeof rows)[number]) => a.duration - b.duration,
        }

        expect(
            rows
                .slice()
                .sort((a, b) =>
                    compareWithSortings(
                        a,
                        b,
                        [
                            { columnKey: 'runs', order: -1 },
                            { columnKey: 'duration', order: -1 },
                        ],
                        (columnKey) => comparators[columnKey as keyof typeof comparators]
                    )
                )
                .map(({ name }) => name)
        ).toEqual(['slow-common', 'fast-common', 'slow-rare'])
    })
})

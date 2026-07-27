import { chunk, range } from 'lib/utils/arrays'

describe('arrays utils', () => {
    describe('range', () => {
        it('creates simple range', () => {
            expect(range(4)).toEqual([0, 1, 2, 3])
        })

        it('creates offset range', () => {
            expect(range(1, 5)).toEqual([1, 2, 3, 4])
        })
    })

    describe('chunk', () => {
        it('splits into evenly-sized chunks', () => {
            expect(chunk([1, 2, 3, 4], 2)).toEqual([
                [1, 2],
                [3, 4],
            ])
        })

        it('leaves a smaller final chunk when not evenly divisible', () => {
            expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]])
        })

        it('returns one chunk when size exceeds length', () => {
            expect(chunk([1, 2], 10)).toEqual([[1, 2]])
        })

        it('returns an empty array for an empty input', () => {
            expect(chunk([], 3)).toEqual([])
        })
    })
})

import { range } from 'lib/utils/arrays'

describe('arrays utils', () => {
    describe('range', () => {
        it('creates simple range', () => {
            expect(range(4)).toEqual([0, 1, 2, 3])
        })

        it('creates offset range', () => {
            expect(range(1, 5)).toEqual([1, 2, 3, 4])
        })
    })
})

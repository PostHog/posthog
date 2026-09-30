import { readNumber } from './propertyReaders'

describe('readNumber', () => {
    it.each([
        ['', null],
        ['  ', null],
        ['0.2', 0.2],
        [0, 0],
        ['abc', null],
        [undefined, null],
    ])('reads %p as %p', (input, expected) => {
        expect(readNumber(input)).toBe(expected)
    })
})

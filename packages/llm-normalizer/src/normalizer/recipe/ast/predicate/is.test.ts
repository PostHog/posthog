import { IsPredicate } from './is'

describe('IsPredicate', () => {
    it('true when the value is one of the listed types', () => {
        expect(new IsPredicate(['string', 'array']).test('hi', true)).toBe(true)
        expect(new IsPredicate(['string', 'array']).test([1], true)).toBe(true)
    })

    it('false for a non-listed type or an absent field', () => {
        expect(new IsPredicate(['string']).test(42, true)).toBe(false)
        expect(new IsPredicate(['string']).test(undefined, false)).toBe(false)
    })
})

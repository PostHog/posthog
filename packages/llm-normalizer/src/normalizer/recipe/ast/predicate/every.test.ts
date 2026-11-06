import { EveryPredicate } from './every'
import { IsPredicate } from './is'

describe('EveryPredicate', () => {
    const allStrings = new EveryPredicate(new IsPredicate(['string']))

    it('true when every element satisfies the inner predicate', () => {
        expect(allStrings.test(['a', 'b', 'c'], true)).toBe(true)
    })

    it('false when any element fails the inner predicate', () => {
        expect(allStrings.test(['a', 2, 'c'], true)).toBe(false)
    })

    it('false for an empty array or a non-array', () => {
        expect(allStrings.test([], true)).toBe(false)
        expect(allStrings.test('not an array', true)).toBe(false)
    })
})

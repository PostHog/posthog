import { InPredicate } from './in'

describe('InPredicate', () => {
    it('true when the value is in the set', () => {
        expect(new InPredicate(['a', 'b', 'c']).test('b', true)).toBe(true)
    })

    it('false when the value is out of the set or absent', () => {
        expect(new InPredicate(['a', 'b']).test('z', true)).toBe(false)
        expect(new InPredicate(['a', 'b']).test(undefined, false)).toBe(false)
    })
})

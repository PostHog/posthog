import { ExistsPredicate } from './exists'

describe('ExistsPredicate', () => {
    it('true when presence matches the expectation', () => {
        expect(new ExistsPredicate(true).test('any', true)).toBe(true)
        expect(new ExistsPredicate(false).test(undefined, false)).toBe(true)
    })

    it('false when presence is the opposite of what is expected', () => {
        expect(new ExistsPredicate(true).test(undefined, false)).toBe(false)
        expect(new ExistsPredicate(false).test('any', true)).toBe(false)
    })
})

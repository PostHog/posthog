import { EqualsPredicate } from './equals'

describe('EqualsPredicate', () => {
    it('true on a strict-equal value that is present', () => {
        expect(new EqualsPredicate('tool').test('tool', true)).toBe(true)
        expect(new EqualsPredicate('tool').test('other', true)).toBe(false)
    })

    it('false when the field is absent, even if the value would match', () => {
        expect(new EqualsPredicate(undefined).test(undefined, false)).toBe(false)
    })
})

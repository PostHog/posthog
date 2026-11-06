import { EqualsPredicate } from './equals'
import { Pattern } from './pattern'
import { ShapePredicate } from './shape'

describe('ShapePredicate', () => {
    const shape = new ShapePredicate(new Pattern({ type: new EqualsPredicate('text') }))

    it('true when the nested object matches the pattern', () => {
        expect(shape.test({ type: 'text', text: 'hi' }, true)).toBe(true)
    })

    it('false for a non-object, null, or absent value', () => {
        expect(shape.test({ type: 'image' }, true)).toBe(false)
        expect(shape.test('text', true)).toBe(false)
        expect(shape.test(null, true)).toBe(false)
        expect(shape.test(undefined, false)).toBe(false)
    })
})

import { EqualsPredicate } from './equals'
import { ExistsPredicate } from './exists'
import { IsPredicate } from './is'
import { Pattern } from './pattern'

describe('Pattern', () => {
    it('true when every field predicate passes', () => {
        const pattern = new Pattern({ role: new EqualsPredicate('user'), content: new IsPredicate(['string']) })
        expect(pattern.matches({ role: 'user', content: 'hi' })).toBe(true)
    })

    it('false when any field predicate fails', () => {
        const pattern = new Pattern({ role: new EqualsPredicate('user'), content: new IsPredicate(['string']) })
        expect(pattern.matches({ role: 'user', content: 42 })).toBe(false)
    })

    it('the $ field applies its predicate to the whole input', () => {
        const pattern = new Pattern({ $: new IsPredicate(['string']) })
        expect(pattern.matches('a bare string')).toBe(true)
        expect(pattern.matches({ not: 'a string' })).toBe(false)
    })

    it('an absent field is reported as not-present to its predicate', () => {
        const pattern = new Pattern({ role: new ExistsPredicate(false) })
        expect(pattern.matches({ content: 'hi' })).toBe(true)
        expect(pattern.matches({ role: 'user' })).toBe(false)
    })
})

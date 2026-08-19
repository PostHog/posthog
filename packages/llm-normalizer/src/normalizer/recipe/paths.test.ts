import { hasField, readField, readPath } from './paths'

describe('paths', () => {
    it('readField returns a present field and readPath walks nested segments', () => {
        expect(readField({ role: 'user' }, 'role')).toBe('user')
        expect(readPath({ a: { b: { c: 1 } } }, ['a', 'b', 'c'])).toBe(1)
    })

    it('hasField reports presence', () => {
        expect(hasField({ role: 'user' }, 'role')).toBe(true)
        expect(hasField({ role: undefined }, 'role')).toBe(true)
    })

    it('all return undefined/false for missing keys or non-object cursors', () => {
        expect(readField({ a: 1 }, 'missing')).toBeUndefined()
        expect(readField('not an object', 'length')).toBeUndefined()
        expect(readPath({ a: {} }, ['a', 'b', 'c'])).toBeUndefined()
        expect(hasField('not an object', 'length')).toBe(false)
    })
})

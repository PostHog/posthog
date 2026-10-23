import { initKeaTests } from '~/test/init'

import { RetainedValues } from './retainedValues'

describe('RetainedValues', () => {
    beforeEach(() => initKeaTests())

    test.each([
        { limit: 'entry count', options: { maxEntries: 3 }, size: 1 },
        { limit: 'total size', options: { maxEntries: 100, maxTotalSize: 10 }, size: 3 },
    ])('evicts the least recently used value when the $limit limit is reached', ({ options, size }) => {
        const values = new RetainedValues<number>({ ttlMs: 60_000, scopeToProject: false, ...options })
        values.set('0', 0, size)
        values.set('1', 1, size)
        values.set('2', 2, size)
        values.get('0')
        values.set('next', 3, size)
        expect(values.get('0')).toBe(0)
        expect(values.get('1')).toBeNull()
        expect(values.get('next')).toBe(3)
    })

    it('does not keep a value larger than the entry limit', () => {
        const values = new RetainedValues<string>({
            maxEntries: 10,
            ttlMs: 60_000,
            maxEntrySize: 3,
            sizeOf: (value) => value.length,
            scopeToProject: false,
        })
        values.set('small', 'abc')
        values.set('large', 'abcd')
        expect(values.get('small')).toBe('abc')
        expect(values.get('large')).toBeNull()
    })
})

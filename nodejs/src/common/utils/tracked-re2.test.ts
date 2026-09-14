import RE2 from 're2'

import { createTrackedRE2 } from './tracked-re2'

describe('createTrackedRE2', () => {
    it('returns the same instance for the same pattern and flags within the cache', () => {
        const a = createTrackedRE2('foo\\d+', undefined, 'test-cache')
        const b = createTrackedRE2('foo\\d+', undefined, 'test-cache')
        expect(a).toBe(b)
    })

    it('returns different instances for different patterns', () => {
        const a = createTrackedRE2('foo', undefined, 'test-cache')
        const b = createTrackedRE2('bar', undefined, 'test-cache')
        expect(a).not.toBe(b)
    })

    it('distinguishes flags in the cache key', () => {
        const a = createTrackedRE2('foo', undefined, 'test-cache')
        const b = createTrackedRE2('foo', 'i', 'test-cache')
        expect(a).not.toBe(b)
    })

    it('cached instances remain usable across repeated exec/test calls', () => {
        const re = createTrackedRE2('sk_(?:live|test)_([A-Za-z0-9]{10,})', undefined, 'test-cache')
        expect(re.test('token sk_live_abcdefghijklmnop')).toBe(true)
        expect(re.exec('token sk_live_abcdefghijklmnop')?.[1]).toBe('abcdefghijklmnop')
        // Reuse after prior exec: no sticky lastIndex (no /g flag)
        expect(re.exec('sk_test_zzzzzzzzzzzz')?.[1]).toBe('zzzzzzzzzzzz')
        expect(re.test('no match here')).toBe(false)
    })
})

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

    it.each([
        ['foo', 'is', 'isfoo', undefined],
        ['foo', 'i', 'ifoo', undefined],
        ['bar', 'si', 'sibar', undefined],
    ])('does not alias (%s, %p) with (%s, %p) in the cache key', (patternA, flagsA, patternB, flagsB) => {
        const a = createTrackedRE2(patternA, flagsA, 'test-cache')
        const b = createTrackedRE2(patternB, flagsB, 'test-cache')
        expect(b).not.toBe(a)
        expect(b.source).toBe(patternB)
        expect(a.source).toBe(patternA)
    })

    it('cached instances remain usable across repeated exec/test calls', () => {
        const re = createTrackedRE2('sk_(?:live|test)_([A-Za-z0-9]{10,})', undefined, 'test-cache')
        expect(re.test('token sk_live_abcdefghijklmnop')).toBe(true)
        expect(re.exec('token sk_live_abcdefghijklmnop')?.[1]).toBe('abcdefghijklmnop')
        // Reuse after prior exec: no sticky lastIndex (no /g flag)
        expect(re.exec('sk_test_zzzzzzzzzzzz')?.[1]).toBe('zzzzzzzzzzzz')
        expect(re.test('no match here')).toBe(false)
    })

    it('does not cache patterns above the per-entry size limit', () => {
        // A customer-controlled pattern can be arbitrarily large; caching even a handful
        // of huge patterns would grow shared ingestion-worker memory without bound.
        const hugePattern = 'a'.repeat(64 * 1024)
        const a = createTrackedRE2(hugePattern, undefined, 'test-cache-huge')
        const b = createTrackedRE2(hugePattern, undefined, 'test-cache-huge')
        // Not cached: each call compiles a fresh instance.
        expect(a).not.toBe(b)
    })

    it('still caches patterns at the boundary size', () => {
        // Just under the limit must remain cached (we do not break the hot path).
        const pattern = 'a'.repeat(1024)
        const a = createTrackedRE2(pattern, undefined, 'test-cache-boundary')
        const b = createTrackedRE2(pattern, undefined, 'test-cache-boundary')
        expect(a).toBe(b)
    })
})

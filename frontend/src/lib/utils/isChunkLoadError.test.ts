import { isChunkLoadError, isLikelyStaleChunkRuntimeError } from './isChunkLoadError'

describe('isChunkLoadError', () => {
    it.each([
        ['webpack ChunkLoadError', { name: 'ChunkLoadError', message: 'Loading chunk 0 failed.' }, true],
        [
            'esbuild dynamic-import failure',
            { name: 'TypeError', message: 'Failed to fetch dynamically imported module: /static/chunk.js' },
            true,
        ],
        [
            'vite alternate dynamic-import failure',
            { name: 'TypeError', message: 'error loading dynamically imported module: /static/chunk.js' },
            true,
        ],
        ['Safari native TypeError: Load failed', { name: 'TypeError', message: 'Load failed' }, true],
        [
            'Firefox native TypeError: NetworkError',
            { name: 'TypeError', message: 'NetworkError when attempting to fetch resource.' },
            true,
        ],
        ['generic TypeError', { name: 'TypeError', message: 'undefined is not a function' }, false],
        ['unrelated Error', { name: 'Error', message: 'something else' }, false],
        ['error with no name or message', {}, false],
    ])('classifies %s', (_label, error, expected) => {
        expect(isChunkLoadError(error)).toBe(expected)
    })

    it.each([
        ['null', null],
        ['undefined', undefined],
        ['string', 'Load failed'],
        ['number', 42],
    ])('returns false for non-object %s', (_label, value) => {
        expect(isChunkLoadError(value)).toBe(false)
    })
})

describe('isLikelyStaleChunkRuntimeError', () => {
    it.each([
        ['short minified identifier g', { name: 'TypeError', message: 'g is not a function' }, true],
        ['short minified identifier h', { name: 'TypeError', message: 'h is not a function' }, true],
        ['two-char minified identifier', { name: 'TypeError', message: 'aB is not a function' }, true],
        [
            'short minified identifier with trailing context',
            { name: 'TypeError', message: 'g is not a function. (In "g(e)", "g" is undefined)' },
            true,
        ],
        // We don't want to match longer names — those are almost always real app bugs.
        ['long identifier', { name: 'TypeError', message: 'undefined is not a function' }, false],
        ['namespaced call', { name: 'TypeError', message: 'this.props.onClick is not a function' }, false],
        ['non-TypeError', { name: 'Error', message: 'g is not a function' }, false],
        ['unrelated TypeError', { name: 'TypeError', message: 'Cannot read properties of null' }, false],
        ['error with no name or message', {}, false],
    ])('classifies %s', (_label, error, expected) => {
        expect(isLikelyStaleChunkRuntimeError(error)).toBe(expected)
    })

    it.each([
        ['null', null],
        ['undefined', undefined],
        ['string', 'g is not a function'],
        ['number', 42],
    ])('returns false for non-object %s', (_label, value) => {
        expect(isLikelyStaleChunkRuntimeError(value)).toBe(false)
    })
})

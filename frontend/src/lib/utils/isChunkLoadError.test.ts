import { isChunkLoadError } from './isChunkLoadError'

describe('isChunkLoadError', () => {
    it.each([
        ['webpack ChunkLoadError', { name: 'ChunkLoadError', message: 'Loading chunk 0 failed.' }, true],
        [
            'esbuild dynamic-import failure',
            { name: 'TypeError', message: 'Failed to fetch dynamically imported module: /static/chunk.js' },
            true,
        ],
        ['Safari native TypeError: Load failed', { name: 'TypeError', message: 'Load failed' }, true],
        [
            'Firefox native TypeError: NetworkError',
            { name: 'TypeError', message: 'NetworkError when attempting to fetch resource.' },
            true,
        ],
        [
            'Firefox dynamic-import failure',
            { name: 'TypeError', message: 'error loading dynamically imported module: /static/chunk.js' },
            true,
        ],
        [
            'WebKit module-script load failure (TypeError)',
            { name: 'TypeError', message: 'Importing a module script failed.' },
            true,
        ],
        [
            'WebKit module-script load failure (plain Error, not TypeError)',
            { name: 'Error', message: 'Importing a module script failed.' },
            true,
        ],
        [
            'Safari link-time binding mismatch (stale deploy)',
            { name: 'SyntaxError', message: "Importing binding name 'D' is not found." },
            true,
        ],
        [
            'Chrome link-time export mismatch (stale deploy)',
            {
                name: 'SyntaxError',
                message: "The requested module '/static/chunk-ABC.js' does not provide an export named 'D'",
            },
            true,
        ],
        [
            'Firefox link-time import mismatch (stale deploy)',
            { name: 'SyntaxError', message: 'import not found: D' },
            true,
        ],
        [
            'Firefox ambiguous indirect export (stale deploy)',
            { name: 'SyntaxError', message: 'ambiguous indirect export: D' },
            true,
        ],
        ['generic TypeError', { name: 'TypeError', message: 'undefined is not a function' }, false],
        ['unrelated SyntaxError', { name: 'SyntaxError', message: 'Unexpected token }' }, false],
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

import { isChunkLoadError, isGenericNetworkTypeError, markAsChunkLoadError } from './isChunkLoadError'

describe('isChunkLoadError', () => {
    it.each([
        ['webpack ChunkLoadError', { name: 'ChunkLoadError', message: 'Loading chunk 0 failed.' }, true],
        [
            'esbuild dynamic-import failure',
            { name: 'TypeError', message: 'Failed to fetch dynamically imported module: /static/chunk.js' },
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
        ['generic TypeError', { name: 'TypeError', message: 'undefined is not a function' }, false],
        ['unrelated Error', { name: 'Error', message: 'something else' }, false],
        ['error with no name or message', {}, false],
        ['Safari native TypeError: Load failed, unmarked', { name: 'TypeError', message: 'Load failed' }, false],
        [
            'Firefox native TypeError: NetworkError, unmarked',
            { name: 'TypeError', message: 'NetworkError when attempting to fetch resource.' },
            false,
        ],
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

    it('treats a generic network TypeError as a chunk load error once marked by retryImport', () => {
        const error = { name: 'TypeError', message: 'Load failed' }
        expect(isChunkLoadError(error)).toBe(false)
        markAsChunkLoadError(error)
        expect(isChunkLoadError(error)).toBe(true)
    })
})

describe('isGenericNetworkTypeError', () => {
    it.each([
        ['Safari native TypeError: Load failed', { name: 'TypeError', message: 'Load failed' }, true],
        [
            'Firefox native TypeError: NetworkError',
            { name: 'TypeError', message: 'NetworkError when attempting to fetch resource.' },
            true,
        ],
        ['generic TypeError', { name: 'TypeError', message: 'undefined is not a function' }, false],
        ['non-TypeError with a matching message', { name: 'Error', message: 'Load failed' }, false],
        ['error with no name or message', {}, false],
    ])('classifies %s', (_label, error, expected) => {
        expect(isGenericNetworkTypeError(error)).toBe(expected)
    })
})

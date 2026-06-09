import { dropChunkLoadExceptions, isChunkLoadError } from './isChunkLoadError'

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

describe('dropChunkLoadExceptions', () => {
    it('passes non-exception events through unchanged', () => {
        const event = { event: '$pageview', properties: { $current_url: '/foo' } }
        expect(dropChunkLoadExceptions(event)).toBe(event)
    })

    it('passes $exception events without a chunk-load error through', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'TypeError', value: 'x is not a function' }] },
        }
        expect(dropChunkLoadExceptions(event)).toBe(event)
    })

    it('drops the Firefox stale-deploy chunk-load error reported by the signal', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    {
                        type: 'TypeError',
                        value: 'error loading dynamically imported module: https://example.com/static/chunk-DWBKWL7J.js',
                    },
                ],
            },
        }
        expect(dropChunkLoadExceptions(event)).toBeNull()
    })

    it('drops webpack ChunkLoadError', () => {
        const event = {
            event: '$exception',
            properties: { $exception_list: [{ type: 'ChunkLoadError', value: 'Loading chunk 0 failed.' }] },
        }
        expect(dropChunkLoadExceptions(event)).toBeNull()
    })

    it('drops wrapped errors where the chunk-load error lives in the cause chain', () => {
        const event = {
            event: '$exception',
            properties: {
                $exception_list: [
                    { type: 'Error', value: 'failed to render scene' },
                    { type: 'TypeError', value: 'Failed to fetch dynamically imported module: /static/chunk.js' },
                ],
            },
        }
        expect(dropChunkLoadExceptions(event)).toBeNull()
    })

    it('tolerates missing properties and missing exception list', () => {
        expect(dropChunkLoadExceptions({ event: '$exception' })).toEqual({ event: '$exception' })
        expect(dropChunkLoadExceptions({ event: '$exception', properties: {} })).toEqual({
            event: '$exception',
            properties: {},
        })
    })

    it('returns null when handed null (matching posthog-js before_send contract)', () => {
        expect(dropChunkLoadExceptions(null)).toBeNull()
    })
})

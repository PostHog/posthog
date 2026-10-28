import { reloadAfterChunkLoadError } from './stableChunks'

describe('reloadAfterChunkLoadError', () => {
    const originalLocation = window.location
    let reload: jest.Mock
    let replace: jest.Mock

    beforeEach(() => {
        document.head.innerHTML = ''
        reload = jest.fn()
        replace = jest.fn()
        Object.defineProperty(window, 'location', {
            configurable: true,
            value: { href: 'https://us.posthog.com/project/1/dashboard?tab=a#panel=x', reload, replace },
        })
    })

    afterEach(() => {
        Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
    })

    it('reloads the same page on the default build', () => {
        reloadAfterChunkLoadError(new TypeError('Failed to resolve module specifier "@c/Abc123".'))

        expect(reload).toHaveBeenCalledTimes(1)
        expect(replace).not.toHaveBeenCalled()
    })

    it.each([
        [
            'a chunk that failed to load',
            new TypeError('Failed to fetch dynamically imported module: /static/chunk.js'),
            'https://us.posthog.com/project/1/dashboard?tab=a&stable_chunks=fallback#panel=x',
        ],
        [
            'a chunk missing from the import map',
            new TypeError('Failed to resolve module specifier "@c/Abc123". Relative references must start with "/".'),
            'https://us.posthog.com/project/1/dashboard?tab=a&stable_chunks=fallback&stable_chunks_unmapped=%40c%2FAbc123#panel=x',
        ],
    ])('loads the page on the default build after %s, keeping the rest of the URL', (_name, error, expectedUrl) => {
        const importMap = document.createElement('script')
        importMap.type = 'importmap'
        document.head.appendChild(importMap)

        reloadAfterChunkLoadError(error)

        expect(reload).not.toHaveBeenCalled()
        expect(replace).toHaveBeenCalledWith(expectedUrl)
    })
})

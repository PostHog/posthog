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
        reloadAfterChunkLoadError()

        expect(reload).toHaveBeenCalledTimes(1)
        expect(replace).not.toHaveBeenCalled()
    })

    it('loads the page on the default build when the stable build fails, keeping the rest of the URL', () => {
        const importMap = document.createElement('script')
        importMap.type = 'importmap'
        document.head.appendChild(importMap)

        reloadAfterChunkLoadError()

        expect(reload).not.toHaveBeenCalled()
        expect(replace).toHaveBeenCalledWith(
            'https://us.posthog.com/project/1/dashboard?tab=a&stable_chunks=fallback#panel=x'
        )
    })
})

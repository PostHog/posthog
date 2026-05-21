import { __RELOAD_GUARD_KEY_FOR_TESTS, reloadOnceForStaleChunk } from './reloadOnceForStaleChunk'

describe('reloadOnceForStaleChunk', () => {
    beforeEach(() => {
        window.localStorage.clear()
    })

    it('calls reload and stamps the guard on a first attempt', () => {
        const reload = jest.fn()
        const before = Date.now()

        const reloaded = reloadOnceForStaleChunk(reload)

        expect(reloaded).toBe(true)
        expect(reload).toHaveBeenCalledTimes(1)
        const storedTimestamp = Number(window.localStorage.getItem(__RELOAD_GUARD_KEY_FOR_TESTS))
        expect(storedTimestamp).toBeGreaterThanOrEqual(before)
    })

    it('skips reload when the guard was set within the window', () => {
        const reload = jest.fn()
        window.localStorage.setItem(__RELOAD_GUARD_KEY_FOR_TESTS, String(Date.now()))

        const reloaded = reloadOnceForStaleChunk(reload)

        expect(reloaded).toBe(false)
        expect(reload).not.toHaveBeenCalled()
    })

    it('reloads again after the guard window has elapsed', () => {
        const reload = jest.fn()
        // 30s ago — well past the 20s guard window
        window.localStorage.setItem(__RELOAD_GUARD_KEY_FOR_TESTS, String(Date.now() - 30_000))

        const reloaded = reloadOnceForStaleChunk(reload)

        expect(reloaded).toBe(true)
        expect(reload).toHaveBeenCalledTimes(1)
    })

    it('still reloads when localStorage is unavailable', () => {
        const reload = jest.fn()
        const getItem = jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
            throw new Error('SecurityError')
        })
        const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('QuotaExceededError')
        })

        try {
            const reloaded = reloadOnceForStaleChunk(reload)
            expect(reloaded).toBe(true)
            expect(reload).toHaveBeenCalledTimes(1)
        } finally {
            getItem.mockRestore()
            setItem.mockRestore()
        }
    })
})

import { startAutoRefresh } from './useDashboardRefresh'

describe('startAutoRefresh', () => {
    beforeEach(() => {
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it('holds refreshes while the page is hidden and runs one when the person comes back', () => {
        const hidden = jest.spyOn(document, 'hidden', 'get').mockReturnValue(false)
        const refresh = jest.fn()
        const stop = startAutoRefresh(30_000, refresh)

        jest.advanceTimersByTime(30_000)
        expect(refresh).toHaveBeenCalledTimes(1)

        hidden.mockReturnValue(true)
        jest.advanceTimersByTime(90_000)
        expect(refresh).toHaveBeenCalledTimes(1)

        hidden.mockReturnValue(false)
        document.dispatchEvent(new Event('visibilitychange'))
        expect(refresh).toHaveBeenCalledTimes(2)

        stop()
        jest.advanceTimersByTime(60_000)
        expect(refresh).toHaveBeenCalledTimes(2)
    })
})

jest.mock('~/toolbar/toolbarLogger', () => ({
    toolbarLogger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

// Keep the real toolbar posthog-js instance but spy on the exception capture helper, so we can
// assert which refresh failures do and don't get reported to error tracking.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

describe('toolbarAuth refreshOAuthTokens', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.resetModules()
        global.fetch = jest.fn()
    })

    const mockRefreshResponse = (status: number): void => {
        ;(global.fetch as jest.Mock).mockResolvedValue({
            ok: status >= 200 && status < 300,
            status,
            json: () => Promise.resolve({}),
        } as Response)
    }

    // A transient 5xx from the OAuth server is recovered from gracefully downstream, so it must not
    // spawn an error-tracking issue; genuine 4xx failures are still reported.
    it.each([
        [503, false],
        [500, false],
        [400, true],
        [401, true],
    ])('status %i captures exception: %s', async (status, shouldCapture) => {
        // Import after jest.mock/resetModules so both modules bind to the same freshly-registered
        // mock (the sucrase transform does not rewire an already-evaluated static import).
        const { refreshOAuthTokens } = await import('~/toolbar/toolbarAuth')
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')
        mockRefreshResponse(status)

        await expect(refreshOAuthTokens('https://ph.example.com', 'client-1', 'refresh-1')).rejects.toThrow(
            `Refresh failed: ${status}`
        )

        expect(captureToolbarException).toHaveBeenCalledTimes(shouldCapture ? 1 : 0)
    })
})

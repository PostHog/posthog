// Keep the real toolbar posthog-js instance (the module inits it at import) and only spy on the
// exception-capture helper. Tests re-import both modules from a reset registry (see beforeEach) so
// the code under test and the assertions share the same mocked `captureToolbarException` — the
// pattern used in index.test.ts.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

const mockFetch = jest.fn()

describe('refreshOAuthTokens', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        jest.resetModules()
        global.fetch = mockFetch
    })

    // A 4xx means a stale/expired/revoked/rotated refresh token — an expected auth-expiry the toolbar
    // handles with a re-auth toast, so it must not spawn an error-tracking exception (the noise being fixed).
    it.each([400, 401, 403, 404])('does not report %s (expected auth-expiry) to error tracking', async (status) => {
        const { refreshOAuthTokens } = await import('~/toolbar/toolbarAuth')
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')
        mockFetch.mockResolvedValueOnce({ ok: false, status, json: async () => ({}) })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).rejects.toThrow(
            `Refresh failed: ${status}`
        )

        expect(captureToolbarException).not.toHaveBeenCalled()
    })

    // 5xx and other unexpected statuses are genuine failures and should still reach error tracking.
    it.each([500, 502, 503])('still reports %s to error tracking', async (status) => {
        const { refreshOAuthTokens } = await import('~/toolbar/toolbarAuth')
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')
        mockFetch.mockResolvedValueOnce({ ok: false, status, json: async () => ({}) })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).rejects.toThrow(
            `Refresh failed: ${status}`
        )

        expect(captureToolbarException).toHaveBeenCalledWith(expect.any(Error), 'token_refresh')
    })

    it('resolves with the tokens and reports nothing on success', async () => {
        const { refreshOAuthTokens } = await import('~/toolbar/toolbarAuth')
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')
        const tokens = { access_token: 'a', refresh_token: 'r', expires_in: 3600 }
        mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => tokens })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).resolves.toEqual(tokens)

        expect(captureToolbarException).not.toHaveBeenCalled()
    })
})

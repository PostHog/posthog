// Spy on the posthog-js capture helper so we can assert what reaches error tracking; keep the
// rest of toolbarPosthogJS real so its module-level init doesn't break.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
}))

const mockFetch = jest.fn()

describe('refreshOAuthTokens', () => {
    beforeEach(() => {
        // The MSW harness replaces global.fetch after module load, so assign per-test. resetModules
        // ensures toolbarAuth re-binds to the mocked capture helper under the mock above.
        jest.resetModules()
        jest.clearAllMocks()
        global.fetch = mockFetch
    })

    it('returns tokens on a successful refresh without capturing', async () => {
        const { refreshOAuthTokens } = await import('~/toolbar/toolbarAuth')
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')
        const tokens = { access_token: 'a', refresh_token: 'r', expires_in: 3600 }
        mockFetch.mockResolvedValue({ ok: true, status: 200, json: async () => tokens })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).resolves.toEqual(tokens)
        expect(captureToolbarException).not.toHaveBeenCalled()
    })

    // A 400 is the expected auth-expiry outcome (invalid_grant / remapped 401/403): it must still
    // throw so callers prompt re-auth, but it must NOT be reported to error tracking. Any other
    // non-ok status (5xx and the like) is genuinely unexpected and must be captured.
    it.each([
        [400, false],
        [500, true],
        [502, true],
        [503, true],
    ])('status %i captures exception: %s', async (status, shouldCapture) => {
        const { refreshOAuthTokens, TokenRefreshError } = await import('~/toolbar/toolbarAuth')
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')
        mockFetch.mockResolvedValue({ ok: false, status, json: async () => ({}) })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).rejects.toBeInstanceOf(TokenRefreshError)
        expect(captureToolbarException).toHaveBeenCalledTimes(shouldCapture ? 1 : 0)
    })
})

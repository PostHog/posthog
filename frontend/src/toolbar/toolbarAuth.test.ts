import { refreshOAuthTokens } from '~/toolbar/toolbarAuth'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'

jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    captureToolbarException: jest.fn(),
    toolbarPosthogJS: { capture: jest.fn() },
}))

const mockFetch = jest.fn()

describe('refreshOAuthTokens', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        global.fetch = mockFetch
    })

    it('returns the parsed tokens on success without reporting anything', async () => {
        const tokens = { access_token: 'a', refresh_token: 'r', expires_in: 3600 }
        mockFetch.mockResolvedValueOnce({ ok: true, status: 200, json: async () => tokens })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).resolves.toEqual(tokens)

        expect(captureToolbarException).not.toHaveBeenCalled()
        expect(toolbarPosthogJS.capture).toHaveBeenCalledWith(
            'toolbar token refresh',
            expect.objectContaining({ status: 'success' })
        )
    })

    // A 4xx means a stale/expired/revoked/rotated refresh token — an expected auth-expiry the toolbar
    // handles with a re-auth toast, so it must not spawn an error-tracking exception (the noise being fixed).
    it.each([400, 401, 403, 404])('treats %s as expected auth-expiry: analytics only, no exception', async (status) => {
        mockFetch.mockResolvedValueOnce({ ok: false, status, json: async () => ({}) })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).rejects.toThrow(
            `Refresh failed: ${status}`
        )

        expect(toolbarPosthogJS.capture).toHaveBeenCalledWith(
            'toolbar token refresh',
            expect.objectContaining({ status: 'error', http_status: status })
        )
        expect(captureToolbarException).not.toHaveBeenCalled()
    })

    // 5xx and other unexpected statuses are genuine failures and should still reach error tracking.
    it.each([500, 502, 503])('still reports %s to error tracking', async (status) => {
        mockFetch.mockResolvedValueOnce({ ok: false, status, json: async () => ({}) })

        await expect(refreshOAuthTokens('https://app', 'client', 'refresh')).rejects.toThrow(
            `Refresh failed: ${status}`
        )

        expect(captureToolbarException).toHaveBeenCalledWith(expect.any(Error), 'token_refresh')
    })
})

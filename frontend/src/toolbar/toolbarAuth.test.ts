import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { refreshOAuthTokens, withTokenRefresh } from '~/toolbar/toolbarAuth'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'

// captureToolbarException delegates to toolbarPosthogJS.captureException with a toolbar_context tag,
// so spying on the underlying method lets us assert which contexts get captured.
function capturedContexts(): string[] {
    return (toolbarPosthogJS.captureException as jest.Mock).mock.calls.map((c) => c[1]?.toolbar_context)
}

function mockRefreshResponse(status: number): void {
    ;(global.fetch as jest.Mock).mockImplementation(() =>
        Promise.resolve({
            ok: status >= 200 && status < 300,
            status,
            json: () => Promise.resolve({ access_token: 'new-access', refresh_token: 'new-refresh', expires_in: 3600 }),
        } as any as Response)
    )
}

describe('toolbar toolbarAuth', () => {
    beforeEach(() => {
        initKeaTests()
        global.fetch = jest.fn()
        jest.spyOn(toolbarPosthogJS, 'captureException').mockReturnValue(undefined as any)
        jest.spyOn(toolbarPosthogJS, 'capture').mockReturnValue(undefined as any)
        jest.spyOn(lemonToast, 'error').mockReturnValue('' as any)
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('refreshOAuthTokens', () => {
        it.each([400, 401, 403])('does not capture an exception for expected auth-expiry status %s', async (status) => {
            mockRefreshResponse(status)
            await expect(refreshOAuthTokens('https://us.posthog.com', 'cid', 'phr_refresh')).rejects.toThrow(
                `Refresh failed: ${status}`
            )
            expect(capturedContexts()).not.toContain('token_refresh')
            // The metric event still fires regardless of status.
            expect(toolbarPosthogJS.capture).toHaveBeenCalledWith(
                'toolbar token refresh',
                expect.objectContaining({ status: 'error', http_status: status })
            )
        })

        it.each([500, 502])('captures an exception for genuine server error %s', async (status) => {
            mockRefreshResponse(status)
            await expect(refreshOAuthTokens('https://us.posthog.com', 'cid', 'phr_refresh')).rejects.toThrow(
                `Refresh failed: ${status}`
            )
            expect(capturedContexts()).toContain('token_refresh')
        })
    })

    describe('withTokenRefresh', () => {
        function mountAuthenticatedLogic(): void {
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'pha_access',
                refreshToken: 'phr_refresh',
                clientId: 'cid',
                uiHost: 'https://us.posthog.com',
            })
            logic.mount()
        }

        it('does not re-capture an exception for an expected auth-expiry refresh failure', async () => {
            mountAuthenticatedLogic()
            mockRefreshResponse(400)

            const original = { status: 401 } as Response
            const result = await withTokenRefresh(original, () => Promise.resolve({ status: 200 } as Response))

            expect(result).toBe(original)
            expect(capturedContexts()).toEqual([])
            expect(lemonToast.error).toHaveBeenCalled()
            expect(toolbarConfigLogic.values.accessToken).toBeNull()
        })

        it('captures an exception for a genuine server error during refresh', async () => {
            mountAuthenticatedLogic()
            mockRefreshResponse(500)

            const original = { status: 401 } as Response
            await withTokenRefresh(original, () => Promise.resolve({ status: 200 } as Response))

            expect(capturedContexts()).toContain('token_refresh_retry')
        })
    })
})

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { initKeaTests } from '~/test/init'
import { refreshOAuthTokens, TokenRefreshAuthError, withTokenRefresh } from '~/toolbar/toolbarAuth'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import * as toolbarPosthogJS from '~/toolbar/toolbarPosthogJS'

// The toolbar bundle is transformed with Sucrase, which does not hoist jest.mock above
// imports — so a module-factory mock never reaches the already-cached binding in
// toolbarAuth. Spy on the real module object instead (exports are accessed lazily at
// call time, so the spy intercepts toolbarAuth's calls).
const captureSpy = jest.spyOn(toolbarPosthogJS, 'captureToolbarException').mockImplementation(() => {})
const eventSpy = jest.spyOn(toolbarPosthogJS.toolbarPosthogJS, 'capture').mockImplementation(() => undefined as any)
const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => '' as any)

global.fetch = jest.fn()

function mockRefreshResponse(status: number, body?: Record<string, unknown>): void {
    ;(global.fetch as jest.Mock).mockResolvedValue({
        ok: status >= 200 && status < 300,
        status,
        json: () => Promise.resolve(body ?? {}),
    } as Response)
}

describe('toolbarAuth', () => {
    beforeEach(() => {
        ;(global.fetch as jest.Mock).mockReset()
        captureSpy.mockClear()
        eventSpy.mockClear()
        toastSpy.mockClear()
    })

    describe('refreshOAuthTokens', () => {
        it('returns tokens on success without reporting', async () => {
            mockRefreshResponse(200, { access_token: 'pha_new', refresh_token: 'phr_new', expires_in: 3600 })

            const tokens = await refreshOAuthTokens('https://us.posthog.com', 'client-id', 'phr_old')

            expect(tokens).toEqual({ access_token: 'pha_new', refresh_token: 'phr_new', expires_in: 3600 })
            expect(captureSpy).not.toHaveBeenCalled()
        })

        // The backend remaps 401/403 to 400, so any 4xx from the refresh endpoint means
        // the refresh token is no longer valid — an expected re-auth signal, not an error.
        it.each([400, 401, 403, 422])('throws TokenRefreshAuthError without reporting on %s', async (status) => {
            mockRefreshResponse(status, { code: 'invalid_grant' })

            await expect(refreshOAuthTokens('https://us.posthog.com', 'client-id', 'phr_old')).rejects.toBeInstanceOf(
                TokenRefreshAuthError
            )
            expect(captureSpy).not.toHaveBeenCalled()
            // The analytics event still fires so refresh-error volume stays observable.
            expect(eventSpy).toHaveBeenCalledWith(
                'toolbar token refresh',
                expect.objectContaining({ status: 'error', http_status: status })
            )
        })

        it.each([500, 502, 503])('captures an exception on genuine failure %s', async (status) => {
            mockRefreshResponse(status, { code: 'token_refresh_failed' })

            const error = await refreshOAuthTokens('https://us.posthog.com', 'client-id', 'phr_old').catch((e) => e)

            expect(error).toBeInstanceOf(Error)
            expect(error).not.toBeInstanceOf(TokenRefreshAuthError)
            expect(error.message).toBe(`Refresh failed: ${status}`)
            expect(captureSpy).toHaveBeenCalledWith(expect.any(Error), 'token_refresh')
        })
    })

    describe('withTokenRefresh', () => {
        beforeEach(async () => {
            initKeaTests()
            // Let the mount-time UI host check resolve so it doesn't clear the tokens.
            ;(global.fetch as jest.Mock).mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve({}) })
            const logic = toolbarConfigLogic.build({
                apiURL: 'http://localhost',
                accessToken: 'pha_token',
                refreshToken: 'phr_refresh',
                clientId: 'client-id',
                uiHost: 'https://us.posthog.com',
            })
            logic.mount()
            await new Promise((resolve) => setTimeout(resolve, 0))
            ;(global.fetch as jest.Mock).mockReset()
            captureSpy.mockClear()
            toastSpy.mockClear()
        })

        it('passes through non-401 responses untouched', async () => {
            const response = { status: 200 } as Response
            const retry = jest.fn()

            const result = await withTokenRefresh(response, retry)

            expect(result).toBe(response)
            expect(retry).not.toHaveBeenCalled()
        })

        it('retries with a fresh access token after a successful refresh', async () => {
            mockRefreshResponse(200, { access_token: 'pha_new', refresh_token: 'phr_new', expires_in: 3600 })
            const retried = { status: 200 } as Response
            const retry = jest.fn().mockResolvedValue(retried)

            const result = await withTokenRefresh({ status: 401 } as Response, retry)

            expect(retry).toHaveBeenCalledWith('pha_new')
            expect(result).toBe(retried)
            expect(captureSpy).not.toHaveBeenCalled()
        })

        it('triggers re-auth without reporting when the refresh token is rejected (400)', async () => {
            mockRefreshResponse(400, { code: 'invalid_grant' })
            const original = { status: 401 } as Response
            const retry = jest.fn()

            const result = await withTokenRefresh(original, retry)

            expect(result).toBe(original)
            expect(retry).not.toHaveBeenCalled()
            expect(toolbarConfigLogic.values.accessToken).toBeNull()
            expect(toastSpy).toHaveBeenCalled()
            expect(captureSpy).not.toHaveBeenCalled()
        })

        it('reports a genuine refresh failure (500) while still triggering re-auth', async () => {
            mockRefreshResponse(500, { code: 'token_refresh_failed' })
            const original = { status: 401 } as Response
            const retry = jest.fn()

            const result = await withTokenRefresh(original, retry)

            expect(result).toBe(original)
            expect(toolbarConfigLogic.values.accessToken).toBeNull()
            expect(toastSpy).toHaveBeenCalled()
            expect(captureSpy).toHaveBeenCalledWith(expect.any(Error), 'token_refresh_retry')
        })
    })
})

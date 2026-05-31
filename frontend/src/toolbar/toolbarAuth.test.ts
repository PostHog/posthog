import { initKeaTests } from '~/test/init'
import { isTransientRefreshError, refreshOAuthTokens, withTokenRefresh } from '~/toolbar/toolbarAuth'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import * as toolbarPosthog from '~/toolbar/toolbarPosthogJS'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { error: jest.fn() },
}))

// Mirrors MAX_REFRESH_ATTEMPTS in toolbarAuth.ts: one retry on transient failures.
const MAX_ATTEMPTS = 2

const okResponse = (): Response =>
    ({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }),
    }) as any as Response

const errorResponse = (status: number): Response => ({ ok: false, status }) as any as Response

describe('toolbarAuth', () => {
    let captureSpy: jest.SpyInstance
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        global.fetch = jest.fn()
        captureSpy = jest.spyOn(toolbarPosthog.toolbarPosthogJS, 'capture').mockImplementation(() => undefined as any)
        captureExceptionSpy = jest
            .spyOn(toolbarPosthog, 'captureToolbarException')
            .mockImplementation(() => undefined)
    })

    afterEach(() => {
        captureSpy.mockRestore()
        captureExceptionSpy.mockRestore()
    })

    describe('refreshOAuthTokens', () => {
        it('returns tokens on success and captures a success analytics event', async () => {
            ;(global.fetch as jest.Mock).mockResolvedValueOnce(okResponse())

            const tokens = await refreshOAuthTokens('http://localhost', 'client', 'refresh')

            expect(tokens).toEqual({ access_token: 'a', refresh_token: 'r', expires_in: 3600 })
            expect(captureExceptionSpy).not.toHaveBeenCalled()
            expect(captureSpy).toHaveBeenCalledWith(
                'toolbar token refresh',
                expect.objectContaining({ status: 'success' })
            )
        })

        it('does not capture an exception for a transient 408, but still captures analytics', async () => {
            ;(global.fetch as jest.Mock).mockResolvedValue(errorResponse(408))

            const error = await refreshOAuthTokens('http://localhost', 'client', 'refresh').catch((e) => e)

            expect(isTransientRefreshError(error)).toBe(true)
            expect(captureExceptionSpy).not.toHaveBeenCalled()
            expect(captureSpy).toHaveBeenCalledWith(
                'toolbar token refresh',
                expect.objectContaining({ status: 'error', http_status: 408, transient: true })
            )
            // 408 is retried once before giving up.
            expect(global.fetch).toHaveBeenCalledTimes(MAX_ATTEMPTS)
        })

        it('retries once and succeeds when the first attempt is a transient failure', async () => {
            ;(global.fetch as jest.Mock).mockResolvedValueOnce(errorResponse(503)).mockResolvedValueOnce(okResponse())

            const tokens = await refreshOAuthTokens('http://localhost', 'client', 'refresh')

            expect(tokens).toEqual({ access_token: 'a', refresh_token: 'r', expires_in: 3600 })
            expect(captureExceptionSpy).not.toHaveBeenCalled()
            expect(global.fetch).toHaveBeenCalledTimes(2)
        })

        it('captures an exception for a genuine auth failure (400) without retrying', async () => {
            ;(global.fetch as jest.Mock).mockResolvedValue(errorResponse(400))

            const error = await refreshOAuthTokens('http://localhost', 'client', 'refresh').catch((e) => e)

            expect(isTransientRefreshError(error)).toBe(false)
            expect(captureExceptionSpy).toHaveBeenCalledWith(error, 'token_refresh')
            expect(global.fetch).toHaveBeenCalledTimes(1)
        })

        it('treats network errors (fetch rejecting) as transient and retries', async () => {
            ;(global.fetch as jest.Mock).mockRejectedValue(new TypeError('Failed to fetch'))

            const error = await refreshOAuthTokens('http://localhost', 'client', 'refresh').catch((e) => e)

            expect(isTransientRefreshError(error)).toBe(true)
            expect(captureExceptionSpy).not.toHaveBeenCalled()
            expect(global.fetch).toHaveBeenCalledTimes(MAX_ATTEMPTS)
        })
    })

    describe('withTokenRefresh', () => {
        beforeEach(() => {
            initKeaTests()
            toolbarConfigLogic
                .build({
                    apiURL: 'http://localhost',
                    accessToken: 'access',
                    refreshToken: 'refresh',
                    clientId: 'client',
                })
                .mount()
        })

        it('does not capture an exception when a 401 refresh fails transiently', async () => {
            ;(global.fetch as jest.Mock).mockResolvedValue(errorResponse(408))

            const result = await withTokenRefresh(errorResponse(401), () => Promise.resolve(okResponse()))

            // The refresh failed, so the original 401 is returned and no retry happens.
            expect(result.status).toBe(401)
            expect(captureExceptionSpy).not.toHaveBeenCalled()
        })

        it('captures an exception when a 401 refresh fails with a genuine auth error', async () => {
            ;(global.fetch as jest.Mock).mockResolvedValue(errorResponse(400))

            await withTokenRefresh(errorResponse(401), () => Promise.resolve(okResponse()))

            expect(captureExceptionSpy).toHaveBeenCalledWith(expect.anything(), 'token_refresh_retry')
        })
    })
})

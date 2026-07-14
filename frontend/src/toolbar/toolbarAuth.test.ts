import { refreshOAuthTokens } from '~/toolbar/toolbarAuth'
import * as toolbarPosthogJSModule from '~/toolbar/toolbarPosthogJS'

global.fetch = jest.fn()

describe('toolbar toolbarAuth refreshOAuthTokens', () => {
    let captureSpy: jest.SpyInstance
    let captureExceptionSpy: jest.SpyInstance

    beforeEach(() => {
        ;(global.fetch as jest.Mock).mockReset()
        captureSpy = jest.spyOn(toolbarPosthogJSModule.toolbarPosthogJS, 'capture').mockImplementation()
        captureExceptionSpy = jest.spyOn(toolbarPosthogJSModule, 'captureToolbarException').mockImplementation()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    function mockRefreshStatus(status: number): void {
        ;(global.fetch as jest.Mock).mockResolvedValue({
            ok: status >= 200 && status < 300,
            status,
            json: () => Promise.resolve({}),
        } as any as Response)
    }

    it.each([400, 401])('does not capture an exception for the expected re-auth status %s', async (status) => {
        mockRefreshStatus(status)

        await expect(refreshOAuthTokens('https://app.posthog.com', 'client', 'refresh')).rejects.toThrow(
            `Refresh failed: ${status}`
        )

        // The analytics event still fires so the failure mode stays measurable...
        expect(captureSpy).toHaveBeenCalledWith(
            'toolbar token refresh',
            expect.objectContaining({ status: 'error', http_status: status })
        )
        // ...but no exception is captured, since this is handled by the re-auth flow.
        expect(captureExceptionSpy).not.toHaveBeenCalled()
    })

    it.each([500, 502])('captures an exception for the unexpected status %s', async (status) => {
        mockRefreshStatus(status)

        await expect(refreshOAuthTokens('https://app.posthog.com', 'client', 'refresh')).rejects.toThrow(
            `Refresh failed: ${status}`
        )

        expect(captureExceptionSpy).toHaveBeenCalledTimes(1)
        expect(captureExceptionSpy).toHaveBeenCalledWith(expect.any(Error), 'token_refresh')
    })
})

// Spy on the exception-capture helper while keeping the real toolbar posthog-js instance, so we can
// assert which refresh failures reach error tracking. Stub `capture` so the analytics event is a no-op.
jest.mock('~/toolbar/toolbarPosthogJS', () => ({
    ...jest.requireActual('~/toolbar/toolbarPosthogJS'),
    captureToolbarException: jest.fn(),
    toolbarPosthogJS: {
        ...jest.requireActual('~/toolbar/toolbarPosthogJS').toolbarPosthogJS,
        capture: jest.fn(),
    },
}))

const mockFetch = jest.fn()

describe('toolbarAuth refreshOAuthTokens', () => {
    beforeEach(() => {
        global.fetch = mockFetch
        jest.clearAllMocks()
        jest.resetModules()
    })

    const refreshWithStatus = async (status: number): Promise<void> => {
        mockFetch.mockResolvedValue({ ok: false, status, json: () => Promise.resolve({}) } as any as Response)
        const { refreshOAuthTokens } = await import('~/toolbar/toolbarAuth')
        await refreshOAuthTokens('https://app.posthog.com', 'client-123', 'refresh-token')
    }

    it.each([408, 429, 500, 502, 503])('does not report transient %i refresh failures', async (status) => {
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')

        await expect(refreshWithStatus(status)).rejects.toThrow(`Refresh failed: ${status}`)

        expect(captureToolbarException).not.toHaveBeenCalled()
    })

    it('reports genuine auth/logic failures (400)', async () => {
        const { captureToolbarException } = await import('~/toolbar/toolbarPosthogJS')

        await expect(refreshWithStatus(400)).rejects.toThrow('Refresh failed: 400')

        expect(captureToolbarException).toHaveBeenCalledWith(expect.any(Error), 'token_refresh')
    })

    it('still emits the analytics event for transient failures', async () => {
        const { toolbarPosthogJS } = await import('~/toolbar/toolbarPosthogJS')

        await expect(refreshWithStatus(503)).rejects.toThrow('Refresh failed: 503')

        expect(toolbarPosthogJS.capture).toHaveBeenCalledWith(
            'toolbar token refresh',
            expect.objectContaining({ status: 'error', http_status: 503 })
        )
    })
})

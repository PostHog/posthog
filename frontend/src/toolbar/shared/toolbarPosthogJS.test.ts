// The real SDK decides which extensions the toolbar's instance runs, so these tests use it.
jest.unmock('posthog-js')

describe('toolbarPosthogJS', () => {
    const originalConsoleError = console.error

    beforeEach(() => {
        jest.useFakeTimers()
        // posthog-js keeps the fetch it finds at import, so load a fresh copy after replacing it.
        jest.resetModules()
        global.fetch = jest.fn(async () => new Response('{}', { status: 200 })) as typeof fetch
    })

    afterEach(() => {
        console.error = originalConsoleError
        jest.useRealTimers()
    })

    it('leaves the host page console alone when remote config turns on console log capture', async () => {
        const hostConsoleError = jest.fn()
        console.error = hostConsoleError

        const { toolbarPosthogJS } = await import('~/toolbar/shared/toolbarPosthogJS')
        toolbarPosthogJS.opt_in_capturing()

        // posthog-js loads its remote config with a script tag, which jsdom never runs, so deliver it by hand.
        ;(window as any)._POSTHOG_REMOTE_CONFIG = {
            [toolbarPosthogJS.config.token]: { config: { logs: { captureConsoleLogs: true } } },
        }
        document.querySelector<HTMLScriptElement>('script[src*="/config.js"]')?.onload?.(new Event('load'))
        await jest.advanceTimersByTimeAsync(1000)

        expect(console.error).toBe(hostConsoleError)
    })
})

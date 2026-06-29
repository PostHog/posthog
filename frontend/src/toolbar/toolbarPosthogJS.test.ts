describe('toolbarPosthogJS', () => {
    it('initializes with unhandled-exception autocapture disabled', async () => {
        // The toolbar runs inside arbitrary customer pages; auto-installed global
        // error handlers would route host-page errors into our internal project.
        // Re-evaluate the module so its module-level posthog.init() call is recorded
        // (it is otherwise cached and evaluated before this test runs).
        jest.resetModules()
        await import('./toolbarPosthogJS')
        const posthog = (await import('posthog-js')).default

        const initCall = (posthog.init as jest.Mock).mock.calls.at(-1)
        expect(initCall).not.toBeUndefined()
        const config = initCall![1]
        expect(config.capture_exceptions).toBe(false)
        expect(config.autocapture).toBe(false)
    })
})

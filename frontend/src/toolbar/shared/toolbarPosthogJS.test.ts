import type { PostHog } from 'posthog-js'

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
        delete (window as any)._POSTHOG_REMOTE_CONFIG
        jest.useRealTimers()
    })

    async function loadWithRemoteConfig(remoteConfig: Record<string, unknown>): Promise<PostHog> {
        // posthog-js applies remote config that is already on the window before it requests any.
        // Preloading it keeps these tests independent of how the SDK fetches config, which changes between
        // SDK versions. The proxy answers any token and records the lookups.
        const tokensLookedUp: string[] = []
        ;(window as any)._POSTHOG_REMOTE_CONFIG = new Proxy(
            {},
            {
                get: (_, token) => {
                    tokensLookedUp.push(String(token))
                    return { config: remoteConfig }
                },
            }
        )
        const { toolbarPosthogJS } = await import('~/toolbar/shared/toolbarPosthogJS')
        toolbarPosthogJS.opt_in_capturing()
        await jest.advanceTimersByTimeAsync(1000)

        // Each test checks that a feature stays off, which also passes when the SDK never read this config.
        expect(tokensLookedUp).toContain(toolbarPosthogJS.config.token)

        return toolbarPosthogJS
    }

    it('leaves the host page console alone when remote config turns on console log capture', async () => {
        const hostConsoleError = jest.fn()
        console.error = hostConsoleError

        await loadWithRemoteConfig({ logs: { captureConsoleLogs: true } })

        expect(console.error).toBe(hostConsoleError)
    })

    it.each([
        ['heatmaps', { heatmaps: true }, (posthog: PostHog) => posthog.heatmaps?.isEnabled],
        [
            'dead clicks',
            { captureDeadClicks: true },
            (posthog: PostHog) => posthog.deadClicksAutocapture?.isEnabled(posthog.deadClicksAutocapture),
        ],
        [
            'web vitals',
            { capturePerformance: { web_vitals: true } },
            (posthog: PostHog) => posthog.webVitalsAutocapture?.isEnabled,
        ],
    ])('keeps %s capture of the host page off when remote config turns it on', async (_, remoteConfig, isEnabled) => {
        const toolbarPosthogJS = await loadWithRemoteConfig(remoteConfig)

        expect(isEnabled(toolbarPosthogJS)).toBe(false)
    })
})

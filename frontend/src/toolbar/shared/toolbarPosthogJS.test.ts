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
        document.querySelectorAll('script[src*="/config.js"]').forEach((script) => script.remove())
        jest.useRealTimers()
    })

    async function loadWithRemoteConfig(remoteConfig: Record<string, unknown>): Promise<PostHog> {
        const { toolbarPosthogJS } = await import('~/toolbar/shared/toolbarPosthogJS')
        toolbarPosthogJS.opt_in_capturing()

        // posthog-js loads its remote config with a script tag, which jsdom never runs, so deliver it by hand.
        ;(window as any)._POSTHOG_REMOTE_CONFIG = {
            [toolbarPosthogJS.config.token]: { config: remoteConfig },
        }
        const configScript = document.querySelector<HTMLScriptElement>('script[src*="/config.js"]')
        expect(configScript?.onload).toEqual(expect.any(Function))
        configScript!.onload!(new Event('load'))
        await jest.advanceTimersByTimeAsync(1000)

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

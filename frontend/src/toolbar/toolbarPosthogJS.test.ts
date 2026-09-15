describe('toolbar posthog-js instance', () => {
    it('stays opted out of autocapture when remote config opts the project in', () => {
        // The global posthog-js mock hides the real config precedence, so load the true library.
        jest.resetModules()
        jest.doMock('posthog-js', () => jest.requireActual('posthog-js'))
        const { toolbarPosthogJS } = require('~/toolbar/toolbarPosthogJS')

        const instance = toolbarPosthogJS as any
        const remoteConfig = {
            ok: true,
            config: {
                autocaptureExceptions: true,
                captureDeadClicks: true,
                capturePerformance: { web_vitals: true },
                heatmaps: true,
            },
        }

        instance.exceptionObserver.onRemoteConfig(remoteConfig)
        instance.deadClicksAutocapture.onRemoteConfig(remoteConfig)
        instance.webVitalsAutocapture.onRemoteConfig(remoteConfig)
        instance.heatmaps.onRemoteConfig(remoteConfig)

        expect(instance.exceptionObserver.isEnabled).toBe(false)
        expect(instance.deadClicksAutocapture.isEnabled(instance.deadClicksAutocapture)).toBe(false)
        expect(instance.webVitalsAutocapture.isEnabled).toBe(false)
        expect(instance.heatmaps.isEnabled).toBe(false)
    })

    it('never installs the console log extension', async () => {
        // The global posthog-js mock hides the real config precedence, so load the true library.
        jest.resetModules()
        jest.doMock('posthog-js', () => jest.requireActual('posthog-js'))
        const { toolbarPosthogJS } = require('~/toolbar/toolbarPosthogJS')

        // The extension installs asynchronously, so let the init task queue drain first.
        await new Promise((resolve) => setTimeout(resolve, 0))

        // A remote `captureConsoleLogs: true` overrides any client value, and it reaches the
        // extension through this subscription. An extension that is never installed never
        // subscribes, so it never patches the customer's console.
        expect((toolbarPosthogJS as any).getExtension('logs')).toBeUndefined()
    })

    it('keeps network payloads and canvas out of a recording when remote config opts them in', () => {
        // The global posthog-js mock hides the real config precedence, so load the true library.
        jest.resetModules()
        jest.doMock('posthog-js', () => jest.requireActual('posthog-js'))
        const { toolbarPosthogJS } = require('~/toolbar/toolbarPosthogJS')
        const { buildNetworkRequestOptions } = require('posthog-js/lib/src/extensions/replay/external/config')

        // Product tours calls startSessionRecording, so the recorder does run on a customer page
        // and resolves these against the internal project's replay settings.
        const networkOptions = buildNetworkRequestOptions(toolbarPosthogJS.config, {
            recordHeaders: true,
            recordBody: true,
            recordPerformance: true,
        })

        expect(networkOptions.recordHeaders).toBe(false)
        expect(networkOptions.recordBody).toBe(false)
        expect(networkOptions.recordPerformance).toBe(false)
        // The recorder reads canvas straight off this value and only falls back to the remote one
        // when the client leaves it unset.
        expect(toolbarPosthogJS.config.session_recording.captureCanvas?.recordCanvas).toBe(false)
    })
})

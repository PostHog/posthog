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
})

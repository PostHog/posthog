import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

export function loadPostHogJS(): void {
    if (window.JS_POSTHOG_API_KEY) {
        posthog.init(window.JS_POSTHOG_API_KEY, {
            opt_out_useragent_filter: window.location.hostname === 'localhost', // we ARE a bot when running in localhost, so we need to enable this opt-out
            api_host: window.JS_POSTHOG_HOST,
            ui_host: window.JS_POSTHOG_UI_HOST,
            rageclick: true,
            persistence: 'localStorage+cookie',
            bootstrap: window.POSTHOG_USER_IDENTITY_WITH_FLAGS ? window.POSTHOG_USER_IDENTITY_WITH_FLAGS : {},
            opt_in_site_apps: true,
            api_transport: 'fetch',
            disable_surveys: window.IMPERSONATED_SESSION,
            __preview_deferred_init_extensions: true,
            loaded: (loadedInstance) => {
                if (loadedInstance.sessionRecording) {
                    loadedInstance.sessionRecording._forceAllowLocalhostNetworkCapture = true
                }

                if (window.IMPERSONATED_SESSION) {
                    loadedInstance.sessionManager?.resetSessionId()
                    loadedInstance.opt_out_capturing()
                } else {
                    loadedInstance.opt_in_capturing()

                    if (loadedInstance.getFeatureFlag(FEATURE_FLAGS.TRACK_MEMORY_USAGE)) {
                        const hasMemory = 'memory' in window.performance
                        if (!hasMemory) {
                            return
                        }

                        const thirtyMinutesInMs = 60000 * 30
                        let intervalId: number | null = null

                        const captureMemory = (
                            visibilityTrigger: 'is_visible' | 'went_invisible' | 'went_visible'
                        ): void => {
                            // this is deprecated and not available in all browsers,
                            // but the supposed standard at https://developer.mozilla.org/en-US/docs/Web/API/Performance/measureUserAgentSpecificMemory
                            // isn't available in Chrome even so 🤷
                            const memory = (window.performance as any).memory
                            if (memory && memory.usedJSHeapSize) {
                                loadedInstance.capture('memory_usage', {
                                    totalJSHeapSize: memory.totalJSHeapSize,
                                    usedJSHeapSize: memory.usedJSHeapSize,
                                    visibility_trigger: visibilityTrigger,
                                    pageIsVisible: document.visibilityState === 'visible',
                                    pageIsFocused: document.hasFocus(),
                                })
                            }
                        }

                        const startInterval = (): void => {
                            if (intervalId !== null) {
                                return
                            }
                            intervalId = window.setInterval(() => captureMemory('is_visible'), thirtyMinutesInMs)
                        }

                        const stopInterval = (): void => {
                            if (intervalId !== null) {
                                clearInterval(intervalId)
                                intervalId = null
                            }
                        }

                        const onVisibilityChange = (): void => {
                            if (document.hidden) {
                                captureMemory('went_invisible')
                                stopInterval()
                            } else {
                                captureMemory('went_visible')
                                startInterval()
                            }
                        }

                        document.addEventListener('visibilitychange', onVisibilityChange)

                        if (!document.hidden) {
                            startInterval()
                        }

                        window.addEventListener('beforeunload', () => {
                            stopInterval()
                            document.removeEventListener('visibilitychange', onVisibilityChange)
                        })
                    }
                }

                // This is a helpful flag to set to automatically reset the recording session on load for testing multiple recordings
                const shouldResetSessionOnLoad = loadedInstance.getFeatureFlag(FEATURE_FLAGS.SESSION_RESET_ON_LOAD)
                if (shouldResetSessionOnLoad) {
                    loadedInstance.sessionManager?.resetSessionId()
                }

                // Make sure we have access to the object in window for debugging
                window.posthog = loadedInstance
            },
            scroll_root_selector: ['main', 'html'],
            autocapture: {
                capture_copied_text: true,
            },
            capture_performance: { web_vitals: true },
            person_profiles: 'always',
            __preview_remote_config: true,
            __preview_flags_v2: true,
            __add_tracing_headers: ['eu.posthog.com', 'us.posthog.com'],
            __preview_eager_load_replay: false,
            __preview_disable_xhr_credentials: true,
        })

        posthog.onFeatureFlags((_flags, _variants, context) => {
            if (inStorybook() || inStorybookTestRunner() || !context?.errorsLoading) {
                return
            }

            posthog.capture('onFeatureFlags error')

            // Track that we failed to load feature flags
            window.POSTHOG_GLOBAL_ERRORS ||= {}
            window.POSTHOG_GLOBAL_ERRORS['onFeatureFlagsLoadError'] = true
        })
    } else {
        posthog.init('fake_token', {
            autocapture: false,
            loaded: function (ph) {
                ph.opt_out_capturing()
            },
        })
    }
}

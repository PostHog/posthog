import posthog from 'posthog-js'

import { Link, lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { getISOWeekString, inStorybook, inStorybookTestRunner } from 'lib/utils'

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
                        // no point in tracking memory if it's not available
                        const hasMemory = 'memory' in window.performance
                        if (!hasMemory) {
                            return
                        }

                        const tenMinuteInMs = 60000 * 10
                        setInterval(() => {
                            // this is deprecated and not available in all browsers,
                            // but the supposed standard at https://developer.mozilla.org/en-US/docs/Web/API/Performance/measureUserAgentSpecificMemory
                            // isn't available in Chrome even so 🤷
                            const memory = (window.performance as any).memory
                            if (memory && memory.usedJSHeapSize) {
                                loadedInstance.capture('memory_usage', {
                                    totalJSHeapSize: memory.totalJSHeapSize,
                                    usedJSHeapSize: memory.usedJSHeapSize,
                                    pageIsVisible: document.visibilityState === 'visible',
                                    pageIsFocused: document.hasFocus(),
                                })
                            }
                        }, tenMinuteInMs)
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

            // Show this toast once per week by using YYYY-WW format for the ID
            const toastId = `toast-feature-flags-error-${getISOWeekString()}`
            if (window.localStorage.getItem(toastId)) {
                return
            }

            posthog.capture('saw feature flags error toast', { toastId })

            lemonToast.warning(
                <div className="flex flex-col gap-2">
                    <span>We couldn't load our internal feature flags.</span>
                    <span>
                        This could be due to the presence of adblockers running in your browser or due to a network
                        issue (e.g. slow wifi). Some features may not be available.
                    </span>
                    <span className="italic">
                        Note: If you use feature flags for your app, you can avoid this issue for your users by using a{' '}
                        <Link to="https://posthog.com/docs/advanced/proxy" target="_blank">
                            reverse proxy
                        </Link>
                        .
                    </span>
                </div>,
                {
                    toastId: toastId,
                    onClose: () => {
                        posthog.capture('closed feature flags error toast', { toastId })
                        window.localStorage.setItem(toastId, 'true')
                    },
                    autoClose: false,
                }
            )
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

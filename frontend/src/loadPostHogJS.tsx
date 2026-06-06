import posthog, { BeforeSendFn, PostHogInterface, SessionRecordingOptions } from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { FEATURE_FLAGS } from 'lib/constants'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

import { startDetachedElementTracking } from './detachedElementTracker'
import { startFramerateTracking } from './framerateTracker'

export const SDK_DEFAULTS_DATE = '2026-05-30'

// Native "the network request never completed" messages. They mean the browser
// could not reach the server at all (offline, DNS, CORS, ad-blocker, connection
// reset). We deliberately keep "Failed to fetch dynamically imported module …"
// (a real, fixable stale-chunk error) out of this list.
const NETWORK_FAILURE_MESSAGES = new Set([
    'Failed to fetch', // Chrome
    'TypeError: Failed to fetch',
    'Load failed', // Safari
    'TypeError: Load failed',
    'NetworkError when attempting to fetch resource.', // Firefox
])

// posthog-js's own internal background traffic — sending session recordings,
// tracing headers, network capture. A network failure whose stack sits here is
// the SDK failing to reach us, surfaced only because we enable
// `error_tracking.__capturePostHogExceptions`. Note this only matches reliably
// for the lazily-loaded recorder script; the rest of the SDK is bundled into our
// own chunks and is indistinguishable from app code until server-side
// symbolication, so a broader sweep belongs in an Error Tracking suppression
// rule, not here.
const POSTHOG_SDK_FRAME_RE = /(posthog-recorder\.js|\/recorder\.js|surveys\.js|exception-autocapture)/

/**
 * Drop `$exception` events that are purely posthog-js's own network-send
 * failures.
 *
 * We intentionally do NOT drop network failures coming from our application code
 * (e.g. `lib/api.ts`): a "Failed to fetch" originating in the app can be a real,
 * our-fault regression — a CORS/CSP misconfig, a removed endpoint, a bad deploy —
 * and we want those visible. We only drop a network failure when every entry in
 * the chain is both a bare network message AND attributable to a posthog-js SDK
 * script, which a flaky/stuck tab can otherwise emit by the thousand.
 */
const dropSdkNetworkExceptions: BeforeSendFn = (event) => {
    if (!event || event.event !== '$exception') {
        return event
    }
    const exceptionList = event.properties?.$exception_list
    if (!Array.isArray(exceptionList) || exceptionList.length === 0) {
        return event
    }
    const everyExceptionIsSdkNetworkNoise = exceptionList.every((exception) => {
        if (!NETWORK_FAILURE_MESSAGES.has(String(exception?.value ?? '').trim())) {
            return false
        }
        const frames = exception?.stacktrace?.frames
        if (!Array.isArray(frames) || frames.length === 0) {
            // No stack to attribute it to → keep it, to stay on the safe side.
            return false
        }
        return frames.some((frame) => POSTHOG_SDK_FRAME_RE.test(String(frame?.source ?? frame?.filename ?? '')))
    })
    return everyExceptionIsSdkNetworkNoise ? null : event
}

const shouldDefer = (): boolean => {
    const sessionId = posthog.get_session_id()
    return sampleOnProperty(sessionId, 0.5)
}

const shouldTrackFramerate = (loadedInstance: PostHogInterface): boolean => {
    return (
        !!window.POSTHOG_APP_CONTEXT?.preflight?.is_debug ||
        !!loadedInstance.getFeatureFlag(FEATURE_FLAGS.TRACK_REACT_FRAMERATE)
    )
}

export interface LoadPostHogJSOptions {
    /**
     * Hook posthog-js's `before_send` so the caller can mutate or drop events before they leave
     * the browser. Used by the exporter app to redact the SharingConfiguration access token from
     * URL-shaped properties on the interview share page — see `frontend/src/exporter/index.tsx`.
     */
    beforeSend?: BeforeSendFn | BeforeSendFn[]
    /**
     * Extra `session_recording` config merged on top of the defaults — useful for overriding URL
     * / network-payload masking when the page renders sensitive bearer tokens in its own URL.
     */
    sessionRecording?: Partial<SessionRecordingOptions>
}

export function loadPostHogJS(options: LoadPostHogJSOptions = {}): void {
    if (window.JS_POSTHOG_API_KEY) {
        posthog.init(window.JS_POSTHOG_API_KEY, {
            opt_out_useragent_filter: window.location.hostname === 'localhost', // we ARE a bot when running in localhost, so we need to enable this opt-out
            api_host: window.JS_POSTHOG_HOST,
            ui_host: window.JS_POSTHOG_UI_HOST,
            defaults: SDK_DEFAULTS_DATE,
            persistence: 'localStorage+cookie',
            cookie_persisted_properties: [
                'prod_interest', // posthog.com sets these based on what docs were browsed
            ],
            bootstrap: window.POSTHOG_USER_IDENTITY_WITH_FLAGS ? window.POSTHOG_USER_IDENTITY_WITH_FLAGS : {},
            opt_in_site_apps: true,
            disable_surveys: window.IMPERSONATED_SESSION,
            disable_product_tours: true,
            opt_out_capturing_by_default: window.IMPERSONATED_SESSION,
            __preview_deferred_init_extensions: shouldDefer(),
            error_tracking: {
                __capturePostHogExceptions: true,
            },
            before_send: [
                dropSdkNetworkExceptions,
                ...(Array.isArray(options.beforeSend)
                    ? options.beforeSend
                    : options.beforeSend
                      ? [options.beforeSend]
                      : []),
            ],
            loaded: (loadedInstance) => {
                if (loadedInstance.sessionRecording) {
                    loadedInstance.sessionRecording._forceAllowLocalhostNetworkCapture = true
                }

                if (window.IMPERSONATED_SESSION) {
                    loadedInstance.sessionManager?.resetSessionId()
                    loadedInstance.opt_out_capturing()
                } else {
                    loadedInstance.opt_in_capturing()

                    if (shouldTrackFramerate(loadedInstance)) {
                        console.info('tracking react framerate')
                        startFramerateTracking(loadedInstance)
                    }

                    if (
                        !!window.POSTHOG_APP_CONTEXT?.preflight?.is_debug ||
                        !!loadedInstance.getFeatureFlag(FEATURE_FLAGS.TRACK_DETACHED_ELEMENTS)
                    ) {
                        startDetachedElementTracking(loadedInstance)
                    }

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
            session_recording: {
                blockSelector: '.ph-replay-block',
                ...options.sessionRecording,
            },
            person_profiles: 'always',
            tracing_headers: ['eu.posthog.com', 'us.posthog.com'],
            __preview_disable_xhr_credentials: true,
            capture_performance: {
                //disabling to investigate if this is associated with memory leak in the posthog app
                web_vitals_attribution: false,
            },
            identity_distinct_id: window.JS_POSTHOG_IDENTITY_DISTINCT_ID,
            identity_hash: window.JS_POSTHOG_IDENTITY_HASH,
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

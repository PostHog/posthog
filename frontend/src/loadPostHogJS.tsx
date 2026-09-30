import posthog, { BeforeSendFn, BrowserMetricsConfig, SessionRecordingOptions } from 'posthog-js'
import { PERSISTENCE_FEATURE_FLAG_ERRORS } from 'posthog-js/lib/src/constants'

import { FEATURE_FLAGS } from 'lib/constants'
import { isOAuthMode } from 'lib/oauth/oauthClient'
import { inStorybook, inStorybookTestRunner } from 'lib/utils/dom'

import { startDetachedElementTracking } from './detachedElementTracker'

export const SDK_DEFAULTS_DATE = '2026-05-30'

// The same hash as posthog-js's own `sampleOnProperty`, so existing sessions keep their side of the
// split. Inlined because the deep import of that extension ships a second copy of @posthog/core.
export function isInDeferredInitSample(sessionId: string): boolean {
    let hash = 0
    for (let i = 0; i < sessionId.length; i++) {
        hash = (hash << 5) - hash + sessionId.charCodeAt(i)
        hash |= 0
    }
    return Math.abs(hash) % 100 < 50
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
    /**
     * Extra `metrics` config merged on top of the defaults. `before_send` and
     * `maskCapturedNetworkRequestFn` do not cover the network metrics channel, so the exporter
     * app uses this to override `network.attributes` and keep the SharingConfiguration access
     * token out of the captured `path`. See `frontend/src/exporter/index.tsx`.
     */
    metrics?: Partial<BrowserMetricsConfig>
}

/*
 * posthog-js builds these codes in `FeatureFlagError`, which its public entry does not export, and
 * whose module carries the whole flag implementation. So they are repeated here instead of
 * deep-imported. Keep them in sync with `FeatureFlagError` in posthog-js.
 */
const API_ERROR_PREFIX = 'api_error_'
/** The codes posthog-js uses when no HTTP response came back at all. */
const TRANSPORT_ERROR_CODES = ['timeout', 'connection_error', 'unknown_error']

export interface FeatureFlagsFailureProperties {
    /** Comma-joined posthog-js error codes, the same vocabulary as `$feature_flag_called`. */
    $feature_flag_error: string
    /** HTTP status of the failed `/flags` request, or null when no response came back. */
    feature_flag_error_status: number | null
    /**
     * Whether an HTTP response came back at all. False points at the network, an ad blocker, or a
     * browser timeout. It does not prove that PostHog never saw the request, because the browser
     * aborts on its own deadline.
     */
    feature_flag_response_received: boolean
}

/**
 * The SDK callback only says that loading failed, so read the codes posthog-js persisted for the
 * same failure. Without them an outage and ad blocker noise look identical on the alert.
 *
 * The codes are SDK internals, so an unreadable or unfamiliar value degrades to `unknown_error`
 * rather than throwing.
 */
export function describeFeatureFlagsFailure(sdkErrors: unknown): FeatureFlagsFailureProperties {
    const codes = Array.isArray(sdkErrors) ? sdkErrors.filter((code): code is string => typeof code === 'string') : []
    if (!codes.length) {
        return {
            $feature_flag_error: 'unknown_error',
            feature_flag_error_status: null,
            feature_flag_response_received: false,
        }
    }

    const apiErrorCode = codes.find((code) => code.startsWith(API_ERROR_PREFIX))
    const apiErrorStatus = apiErrorCode?.slice(API_ERROR_PREFIX.length)

    return {
        $feature_flag_error: codes.join(','),
        // A suffix that is not a status would parse to NaN, which is not a value worth capturing.
        feature_flag_error_status: apiErrorStatus && /^\d{3}$/.test(apiErrorStatus) ? Number(apiErrorStatus) : null,
        feature_flag_response_received: !codes.some((code) => TRANSPORT_ERROR_CODES.includes(code)),
    }
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
            __preview_deferred_init_extensions: isInDeferredInitSample(posthog.get_session_id()),
            error_tracking: {
                __capturePostHogExceptions: true,
            },
            metrics: { network: true, serviceName: 'posthog-app', ...options.metrics },
            before_send: options.beforeSend,
            loaded: (loadedInstance) => {
                if (loadedInstance.sessionRecording) {
                    loadedInstance.sessionRecording._forceAllowLocalhostNetworkCapture = true
                }

                if (window.IMPERSONATED_SESSION) {
                    loadedInstance.sessionManager?.resetSessionId()
                    loadedInstance.opt_out_capturing()
                } else {
                    loadedInstance.opt_in_capturing()

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
                streamNetworkBody: true,
                ...options.sessionRecording,
            },
            person_profiles: 'always',
            // posthog-js patches fetch to add X-POSTHOG-* tracing headers to these hosts. In OAuth
            // mode the app's own /api calls go cross-origin to one of them, where the cloud CORS
            // allowlist rejects those headers — so disable the feature then.
            tracing_headers: isOAuthMode() ? [] : ['eu.posthog.com', 'us.posthog.com'],
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

            posthog.capture('onFeatureFlags error', {
                ...describeFeatureFlagsFailure(posthog.persistence?.props?.[PERSISTENCE_FEATURE_FLAG_ERRORS]),
                // The callback argument holds enabled flags only, so read the cache for its real
                // size. Zero means the app fell back to nothing.
                feature_flag_count: Object.keys(posthog.featureFlags?.getFlagVariants() ?? {}).length,
                // Separates a machine that is offline from a request that only our endpoint refused.
                browser_online: window.navigator.onLine,
            })

            // Track that we failed to load feature flags
            window.POSTHOG_GLOBAL_ERRORS ||= {}
            window.POSTHOG_GLOBAL_ERRORS['onFeatureFlagsLoadError'] = true
        })
    } else {
        posthog.init('fake_token', {
            autocapture: false,
            // Pages without a project key only need `posthog` calls to be safe no-ops. Without this,
            // init() fetches remote config and flags for the placeholder token from PostHog Cloud
            // before `loaded` can opt out.
            advanced_disable_flags: true,
            // `loaded` runs at the end of init(). An event captured before then stays in the request
            // queue, and the queue sends it to PostHog Cloud on page unload even after the opt-out.
            opt_out_capturing_by_default: true,
            loaded: function (ph) {
                ph.opt_out_capturing()
            },
        })
    }
}

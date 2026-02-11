import posthog from 'posthog-js'
import { sampleOnProperty } from 'posthog-js/lib/src/extensions/sampling'

import { FEATURE_FLAGS } from 'lib/constants'
import { inStorybook, inStorybookTestRunner } from 'lib/utils'

export const SDK_DEFAULTS_DATE = '2026-01-30'

const shouldDefer = (): boolean => {
    const sessionId = posthog.get_session_id()
    return sampleOnProperty(sessionId, 0.5)
}

export function loadPostHogJS(): void {
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
            disable_product_tours: window.IMPERSONATED_SESSION,
            __preview_deferred_init_extensions: shouldDefer(),
            error_tracking: {
                __capturePostHogExceptions: true,
            },
            loaded: (loadedInstance) => {
                if (loadedInstance.sessionRecording) {
                    loadedInstance.sessionRecording._forceAllowLocalhostNetworkCapture = true
                }

                if (window.IMPERSONATED_SESSION) {
                    loadedInstance.sessionManager?.resetSessionId()
                    loadedInstance.opt_out_capturing()
                } else {
                    loadedInstance.opt_in_capturing()

                    const shouldTrackFramerate = sampleOnProperty(loadedInstance.get_session_id(), 0.1)
                    if (shouldTrackFramerate) {
                        const LONG_FRAME_THRESHOLD_MS = 50
                        const CAPTURE_INTERVAL_MS = 30_000

                        let rafId: number | null = null
                        let previousTimestamp: number | null = null
                        let frameCount = 0
                        let frameTimeSum = 0
                        let shortestFrame = Infinity
                        let longestFrame = 0
                        let longFrameCount = 0
                        let measurementStart = 0

                        const resetStats = (): void => {
                            previousTimestamp = null
                            frameCount = 0
                            frameTimeSum = 0
                            shortestFrame = Infinity
                            longestFrame = 0
                            longFrameCount = 0
                            measurementStart = performance.now()
                        }

                        const captureFramerate = (): void => {
                            if (frameCount === 0) {
                                return
                            }
                            const elapsed = performance.now() - measurementStart
                            const avgFrameTime = frameTimeSum / frameCount
                            loadedInstance.capture('$$framerate', {
                                avg_fps: Math.round((frameCount / elapsed) * 1000),
                                avg_frame_time_ms: Math.round(avgFrameTime * 100) / 100,
                                min_frame_time_ms: Math.round(shortestFrame * 100) / 100,
                                max_frame_time_ms: Math.round(longestFrame * 100) / 100,
                                long_frame_count: longFrameCount,
                                total_frames: frameCount,
                                measurement_duration_ms: Math.round(elapsed),
                            })
                            resetStats()
                        }

                        const onAnimationFrame = (timestamp: number): void => {
                            if (previousTimestamp !== null) {
                                const delta = timestamp - previousTimestamp
                                frameCount++
                                frameTimeSum += delta
                                if (delta < shortestFrame) {
                                    shortestFrame = delta
                                }
                                if (delta > longestFrame) {
                                    longestFrame = delta
                                }
                                if (delta > LONG_FRAME_THRESHOLD_MS) {
                                    longFrameCount++
                                }
                            }
                            previousTimestamp = timestamp
                            rafId = requestAnimationFrame(onAnimationFrame)
                        }

                        let captureIntervalId: number | null = null

                        const startTracking = (): void => {
                            if (rafId !== null) {
                                return
                            }
                            resetStats()
                            rafId = requestAnimationFrame(onAnimationFrame)
                            captureIntervalId = window.setInterval(captureFramerate, CAPTURE_INTERVAL_MS)
                        }

                        const stopTracking = (): void => {
                            if (rafId !== null) {
                                cancelAnimationFrame(rafId)
                                rafId = null
                            }
                            if (captureIntervalId !== null) {
                                clearInterval(captureIntervalId)
                                captureIntervalId = null
                            }
                        }

                        const onFramerateVisibilityChange = (): void => {
                            if (document.hidden) {
                                captureFramerate()
                                stopTracking()
                            } else {
                                startTracking()
                            }
                        }

                        document.addEventListener('visibilitychange', onFramerateVisibilityChange)

                        if (!document.hidden) {
                            startTracking()
                        }

                        window.addEventListener('beforeunload', () => {
                            stopTracking()
                            document.removeEventListener('visibilitychange', onFramerateVisibilityChange)
                        })
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
            },
            person_profiles: 'always',
            __preview_remote_config: true,
            __preview_flags_v2: true,
            __add_tracing_headers: ['eu.posthog.com', 'us.posthog.com'],
            __preview_disable_xhr_credentials: true,
            external_scripts_inject_target: 'head',
            capture_performance: {
                //disabling to investigate if this is associated with memory leak in the posthog app
                web_vitals_attribution: false,
            },
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

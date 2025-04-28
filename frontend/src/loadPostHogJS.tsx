import * as Sentry from '@sentry/react'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog, { CaptureResult, PostHogConfig } from 'posthog-js'

interface WindowWithCypressCaptures extends Window {
    // our Cypress tests will use this to check what events were sent to PostHog
    _cypress_posthog_captures?: CaptureResult[]
    // cypress puts this on the window, so we can check for it to see if Cypress is running
    Cypress?: any
}

const configWithSentry = (config: Partial<PostHogConfig>): Partial<PostHogConfig> => {
    if ((window as any).SENTRY_DSN) {
        config.on_xhr_error = (failedRequest: XMLHttpRequest) => {
            const status = failedRequest.status
            const statusText = failedRequest.statusText || 'no status text in error'
            Sentry.captureException(
                new Error(`Failed with status ${status} while sending to PostHog. Message: ${statusText}`),
                { tags: { status, statusText } }
            )
        }
    }
    return config
}

export function loadPostHogJS(): void {
    if (window.JS_POSTHOG_API_KEY) {
        posthog.init(
            window.JS_POSTHOG_API_KEY,
            configWithSentry({
                opt_out_useragent_filter: window.location.hostname === 'localhost', // we ARE a bot when running in localhost, so we need to enable this opt-out
                api_host: window.JS_POSTHOG_HOST,
                ui_host: window.JS_POSTHOG_UI_HOST,
                rageclick: true,
                persistence: 'localStorage+cookie',
                bootstrap: window.POSTHOG_USER_IDENTITY_WITH_FLAGS ? window.POSTHOG_USER_IDENTITY_WITH_FLAGS : {},
                opt_in_site_apps: true,
                api_transport: 'fetch',
                before_send: (payload) => {
                    const win = window as WindowWithCypressCaptures
                    if (win.Cypress && payload) {
                        win._cypress_posthog_captures = win._cypress_posthog_captures || []
                        win._cypress_posthog_captures.push(payload)
                    }
                    return payload
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
                    }

                    const Cypress = (window as WindowWithCypressCaptures).Cypress

                    if (Cypress) {
                        Object.entries(Cypress.env()).forEach(([key, value]) => {
                            if (key.startsWith('POSTHOG_PROPERTY_')) {
                                loadedInstance.register_for_session({
                                    [key.replace('POSTHOG_PROPERTY_', 'E2E_TESTING_').toLowerCase()]: value,
                                })
                            }
                        })
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
            })
        )
    } else {
        posthog.init('fake token', {
            autocapture: false,
            loaded: function (ph) {
                ph.opt_out_capturing()
            },
        })
    }

    if (window.SENTRY_DSN) {
        Sentry.init({
            dsn: window.SENTRY_DSN,
            environment: window.SENTRY_ENVIRONMENT,
            ...(location.host.includes('posthog.com') && {
                integrations: [new posthog.SentryIntegration(posthog, 'posthog', 1899813, undefined, '*')],
            }),
        })
    }
}

import * as Sentry from '@sentry/react'
import { FEATURE_FLAGS } from 'lib/constants'
import posthog, { PostHogConfig } from 'posthog-js'

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
                api_host: window.JS_POSTHOG_HOST,
                rageclick: true,
                persistence: 'localStorage+cookie',
                bootstrap: window.POSTHOG_USER_IDENTITY_WITH_FLAGS ? window.POSTHOG_USER_IDENTITY_WITH_FLAGS : {},
                opt_in_site_apps: true,
                loaded: (posthog) => {
                    if (posthog.sessionRecording) {
                        posthog.sessionRecording._forceAllowLocalhostNetworkCapture = true
                    }

                    if (window.IMPERSONATED_SESSION) {
                        posthog.opt_out_capturing()
                    } else {
                        posthog.opt_in_capturing()
                    }
                },
            })
        )

        const Cypress = (window as any).Cypress
        if (Cypress) {
            Object.entries(Cypress.env()).forEach(([key, value]) => {
                if (key.startsWith('POSTHOG_PROPERTY_')) {
                    posthog.register_for_session({
                        [key.replace('POSTHOG_PROPERTY_', 'E2E_TESTING_').toLowerCase()]: value,
                    })
                }
            })
        }

        // This is a helpful flag to set to automatically reset the recording session on load for testing multiple recordings
        const shouldResetSessionOnLoad = posthog.getFeatureFlag(FEATURE_FLAGS.SESSION_RESET_ON_LOAD)
        if (shouldResetSessionOnLoad) {
            posthog.sessionManager?.resetSessionId()
        }
        // Make sure we have access to the object in window for debugging
        window.posthog = posthog
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
                integrations: [new posthog.SentryIntegration(posthog, 'posthog', 1899813)],
            }),
        })
    }
}

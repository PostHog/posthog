import posthog, { PostHogConfig } from 'posthog-js'
import 'posthog-js/dist/recorder'
import * as Sentry from '@sentry/react'
import { FEATURE_FLAGS } from 'lib/constants'

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
                debug: window.JS_POSTHOG_SELF_CAPTURE,
                bootstrap: !!window.POSTHOG_USER_IDENTITY_WITH_FLAGS ? window.POSTHOG_USER_IDENTITY_WITH_FLAGS : {},
                opt_in_site_apps: true,
            })
        )

        // This is a helpful flag to set to automatically reset the recording session on load for testing multiple recordings
        const shouldResetSessionOnLoad = posthog.getFeatureFlag(FEATURE_FLAGS.SESSION_RESET_ON_LOAD)
        if (shouldResetSessionOnLoad) {
            posthog.sessionManager.resetSessionId()
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

    if ((window as any).SENTRY_DSN) {
        Sentry.init({
            dsn: (window as any).SENTRY_DSN,
            ...(window.location.host.indexOf('app.posthog.com') > -1 && {
                integrations: [new posthog.SentryIntegration(posthog, 'posthog2', 1899813)],
            }),
        })
    }
}

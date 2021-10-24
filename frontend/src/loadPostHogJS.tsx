import posthog from 'posthog-js'
import * as Sentry from '@sentry/browser'

const configWithSentry = (config: posthog.Config): posthog.Config => {
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
                // eslint-disable-next-line @typescript-eslint/ban-ts-comment
                // @ts-ignore
                _capture_metrics: true,
                rageclick: true,
                debug: window.JS_POSTHOG_SELF_CAPTURE,
                persistence: 'localStorage+cookie',
            })
        )
        // Make sure we have access to the object in window for debugging
        window.posthog = posthog
    } else {
        posthog.init(
            'fake token',
            configWithSentry({
                autocapture: false,
                loaded: function (ph) {
                    ph.opt_out_capturing()
                },
            })
        )
    }

    if ((window as any).SENTRY_DSN) {
        Sentry.init({
            dsn: (window as any).SENTRY_DSN,
            ...(window.location.host.indexOf('app.posthog.com') > -1 && {
                integrations: [new posthog.SentryIntegration(posthog, 'posthog', 1899813)],
            }),
        })
    }
}

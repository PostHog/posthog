import posthog from 'posthog-js'
import * as Sentry from '@sentry/browser'

export function loadPostHogJS(): void {
    if (window.JS_POSTHOG_API_KEY) {
        posthog.init(window.JS_POSTHOG_API_KEY, {
            api_host: window.JS_POSTHOG_HOST,
            // eslint-disable-next-line @typescript-eslint/ban-ts-comment
            // @ts-ignore
            _capture_metrics: true,
            rageclick: true,
        })
        // Make sure we have access to the object in window for debugging
        window.posthog = posthog
    } else {
        posthog.init('fake token', {
            autocapture: false,
            loaded: function (posthog) {
                posthog.opt_out_capturing()
            },
        })
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

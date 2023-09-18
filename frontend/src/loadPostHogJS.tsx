import posthog, { PostHogConfig } from 'posthog-js'
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

const maskEmails = (text: string): string => {
    // A simple email regex - you may want to use something more advanced
    const emailRegex = /(\S+)@(\S+\.\S+)/g

    return text.replace(emailRegex, (_match, g1, g2) => {
        // Replace each email with asterisks - ben@posthog.com becomes ***@***********
        return '*'.repeat(g1.length) + '@' + '*'.repeat(g2.length)
    })
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
                    if (posthog.webPerformance) {
                        posthog.webPerformance._forceAllowLocalhost = true
                    }

                    if (window.IMPERSONATED_SESSION) {
                        posthog.opt_out_capturing()
                    } else {
                        posthog.opt_in_capturing()
                    }
                },
                session_recording: {
                    maskAllInputs: true,
                    maskInputFn: (text, element) => {
                        const maskTypes = ['email', 'password']

                        if (
                            maskTypes.indexOf(element?.attributes['type']?.value) !== -1 ||
                            maskTypes.indexOf(element?.attributes['id']?.value) !== -1
                        ) {
                            return '*'.repeat(text.length)
                        }
                        return maskEmails(text)
                    },
                    maskTextSelector: '*',
                    maskTextFn(text) {
                        return maskEmails(text)
                    },
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

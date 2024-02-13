/**
 * This will redirect the user to the correct subdomain if they're logged in to a different instance.
 *
 * It will only work for app. and eu. subdomains and other subdomains will need to be added manually
 *
 * There's an e2e test for this.
 *
 * ## Local testing
 *
 * To test this locally, you can edit your /etc/hosts to add a subdomain redirect
 *
 * Add the following line to your host file:
 * 127.0.0.1 app.posthogtest.com
 *
 * Then set the following cookies locally:
 * document.cookie = 'ph_current_instance="https://eu.posthog.com"';
 * document.cookie = "is-logged-in=1";
 *
 * Then go to http://app.posthogtest.com:8000/login?next=/apps
 * And it will update the subdomain, taking you to the following link
 * http://eu.posthogtest.com:8000/login?next=/apps
 */

import { lemonToast } from '@posthog/lemon-ui'
import { captureException } from '@sentry/react'
import { getCookie } from 'lib/api'

// cookie values
const PH_CURRENT_INSTANCE = 'ph_current_instance'

const REDIRECT_TIMEOUT = 2500

type Subdomain = 'eu' | 'us'

export function cleanedCookieSubdomain(loggedInInstance: string | null): Subdomain | null {
    try {
        // replace '"' as for some reason the cookie value is wrapped in quotes e.g. "https://eu.posthog.com"
        const url = loggedInInstance?.replace(/"/g, '')
        if (!url) {
            return null
        }
        // convert to URL, so that we can be sure we're dealing with a valid URL
        const hostname = new URL(url).hostname
        switch (hostname) {
            case 'eu.posthog.com':
                return 'eu'
            case 'us.posthog.com':
                return 'us'
            default:
                return null
        }
    } catch (e) {
        // let's not allow errors in this code break the log-in page 🤞
        captureException(e, { extra: { loggedInInstance } })
        return null
    }
}

function regionFromSubdomain(subdomain: Subdomain): 'EU' | 'US' {
    switch (subdomain) {
        case 'us':
            return 'US'
        case 'eu':
            return 'EU'
    }
}

export function redirectIfLoggedInOtherInstance(): (() => void) | undefined {
    const currentSubdomain = window.location.hostname.split('.')[0]

    const loggedInInstance = getCookie(PH_CURRENT_INSTANCE)
    const loggedInSubdomain = cleanedCookieSubdomain(loggedInInstance)

    if (!loggedInSubdomain) {
        return // not logged into another subdomain
    }

    const loggedIntoOtherSubdomain = loggedInSubdomain !== currentSubdomain

    if (loggedIntoOtherSubdomain) {
        const newUrl = new URL(window.location.href)
        newUrl.hostname = newUrl.hostname.replace(currentSubdomain, loggedInSubdomain)

        let cancelClicked = false

        const closeToastAction = (): void => {
            if (cancelClicked) {
                return
            }
            window.location.assign(newUrl.href)
        }

        lemonToast.info(
            `Redirecting to your logged-in account in the Cloud ${regionFromSubdomain(loggedInSubdomain)} region`,
            {
                button: {
                    label: 'Cancel',
                    action: () => {
                        cancelClicked = true
                    },
                },
                onClose: closeToastAction,
                // we want to force the user to click the cancel button as otherwise the default close will still redirect
                closeButton: false,
                autoClose: REDIRECT_TIMEOUT,
            }
        )
    }
}

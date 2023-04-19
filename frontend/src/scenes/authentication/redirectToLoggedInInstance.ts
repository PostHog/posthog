/**
 * To test this locally, you can edit your /etc/hosts to add a subdomain redirect
 *
 * Add the following line to your host file:
 * 127.0.0.1 app.posthogtest.com
 *
 * Then set the following cookies locally:
 * document.cookie = "ph_current_instance=eu.posthog.com";
 * document.cookie = "is-logged-in=1";
 *
 * Then go to http://app.posthogtest.com:8000/login?next=/apps
 * And you'll be redirected to http://eu.posthogtest.com:8000/apps
 */

import { lemonToast } from '@posthog/lemon-ui'
import { getCookie } from 'lib/api'

const PH_CURRENT_INSTANCE = 'ph_current_instance'

const IS_LOGGED_IN = 'is-logged-in'

const REDIRECT_TIMEOUT = 3000

const EU_SUBDOMAIN = 'eu'
const US_SUBDOMAIN = 'app'

const NEXT_URL_PARAM = 'next'

export function redirectIfLoggedInOtherInstance(): (() => void) | undefined {
    debugger
    const urlParams = new URLSearchParams(window.location.search)
    if (!urlParams.get(NEXT_URL_PARAM) || urlParams.get(NEXT_URL_PARAM) == '/') {
        return // no next param, so return early
    }

    const currentSubdomain = window.location.hostname.split('.')[0]

    const currentCookie = document.cookie
    console.log('current cookie', currentCookie)

    const loggedInSubdomain = getCookie(PH_CURRENT_INSTANCE)
        ?.split('.')[0]
        ?.replace('https://', '')
        ?.replace('http://', '')

    // when they are logged out, ph_instance is not removed.
    // therefore, use is-logged-in cookie to determine if they are logged in
    // note: this seems to be set when logged in and removed when not
    // however I can't find the code where it is set and removed so potentially unreliable
    const isLoggedIn = getCookie(IS_LOGGED_IN)

    if (!loggedInSubdomain || !isLoggedIn) {
        return // not logged into another subdomain
    }

    if (loggedInSubdomain !== US_SUBDOMAIN && loggedInSubdomain !== EU_SUBDOMAIN) {
        return // don't redirect to invalid subdomains
    }

    const loggedIntoOtherSubdomain = loggedInSubdomain !== currentSubdomain

    if (loggedIntoOtherSubdomain) {
        const newUrl = new URL(window.location.href)

        if (newUrl.hostname.split('.').length > 1) {
            console.log('redirecting to', newUrl.hostname.replace(currentSubdomain, loggedInSubdomain))
            newUrl.hostname = newUrl.hostname.replace(currentSubdomain, loggedInSubdomain)
        } else {
            // if there is no subdomain, add one (useful for the cypress tests)
            console.log('redirecting to base url', loggedInSubdomain + '.' + newUrl.hostname)
            newUrl.hostname = loggedInSubdomain + '.' + newUrl.hostname + newUrl.port ? ':' + newUrl.port : ''
        }
        const redirectTimeout = setTimeout(() => {
            window.location.assign(newUrl)
        }, REDIRECT_TIMEOUT)

        lemonToast.info('Redirecting to ' + (loggedInSubdomain == US_SUBDOMAIN ? 'the US cloud' : 'the EU cloud'), {
            button: {
                label: 'Cancel',
                action: () => {
                    clearTimeout(redirectTimeout)
                },
            },
            // don't pause it would give the impression that the redirect has been paused, which it hasn't
            // could instead do a callback on hover action and then restart the timeout from where it left off after
            pauseOnHover: false,
            autoClose: REDIRECT_TIMEOUT,
        })

        return () => {
            clearTimeout(redirectTimeout)
        }
    }
}

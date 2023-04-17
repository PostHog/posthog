import { lemonToast } from '@posthog/lemon-ui'
import { PH_CURRENT_INSTANCE } from 'lib/constants'

const REDIRECT_TIMEOUT = 3000

const EU_SUBDOMAIN = 'eu'
const US_SUBDOMAIN = 'app'

const NEXT_URL_PARAM = 'next'

export function redirectIfLoggedInOtherInstance(): (() => void) | undefined {
    const urlParams = new URLSearchParams(window.location.search)
    if (!urlParams.get(NEXT_URL_PARAM) || urlParams.get(NEXT_URL_PARAM) == '/') {
        return // no next param, so return early
    }

    const currentSubdomain = window.location.hostname.split('.')[0]

    const loggedInSubdomain = document.cookie
        ?.split('; ')
        ?.find((row) => row.startsWith(PH_CURRENT_INSTANCE))
        ?.split('=')[1]
        ?.split('.')[0]
        ?.replace('https://', '')
        ?.replace('http://', '')

    if (!loggedInSubdomain) {
        return // not logged into another subdomain
    }

    // TODO: check they are actually logged in i.e. valid cookie rather than just ph_instance
    // as the ph_instance doesn't seem to be removed when they are logged out

    if (loggedInSubdomain !== US_SUBDOMAIN && loggedInSubdomain !== EU_SUBDOMAIN) {
        return // don't redirect to invalid subdomains
    }

    const loggedIntoOtherSubdomain = loggedInSubdomain !== currentSubdomain

    if (loggedIntoOtherSubdomain) {
        const newUrl = new URL(window.location.href)
        newUrl.hostname = newUrl.hostname.replace(currentSubdomain, loggedInSubdomain)
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

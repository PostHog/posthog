import { lemonToast } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { ApiError, isCSRFTokenError } from 'lib/api-error'
import { isOAuthMode } from 'lib/oauth/oauthClient'

export const CSRF_COOKIE_NAME = 'posthog_csrftoken'

const CSRF_TOKEN_ENDPOINT = '/api/csrf_token/'

/**
 * Whether a rejected request should be repeated with a new CSRF token. A tab open longer than its
 * cookie keeps a working session but loses its token, and only a document render used to set a new
 * one, so every request failed until the person opened a new tab. Failing that, a reload is offered,
 * because nothing else in the app can set the cookie. OAuth mode sends no CSRF token at all.
 *
 * The status is read before the body, so a response that cannot be a CSRF rejection is never cloned
 * or parsed. The clone leaves the original for the caller to build its own error from.
 */
export async function recoverFromCSRFRejection(response: Response, isRetry: boolean): Promise<boolean> {
    if (response.status !== 403 || isOAuthMode()) {
        return false
    }
    if (!isCSRFTokenError(await ApiError.fromResponse(response.clone()))) {
        return false
    }
    if (!isRetry && (await refreshCSRFToken())) {
        return true
    }
    promptReloadForCSRF()
    return false
}

/**
 * One in-flight refresh shared by every caller. A scene issues its requests together, so they fail
 * together, and per-request refreshes would race over which cookie every retry has to use.
 */
let inFlightRefresh: Promise<boolean> | null = null

async function refreshCSRFToken(): Promise<boolean> {
    if (!inFlightRefresh) {
        inFlightRefresh = fetchCSRFToken().finally(() => {
            inFlightRefresh = null
        })
    }
    return await inFlightRefresh
}

// A bare `fetch` rather than `api.get`, because this runs inside the failure path of every request
// and routing it back through that path would let a failing token endpoint recurse.
async function fetchCSRFToken(): Promise<boolean> {
    try {
        const response = await fetch(CSRF_TOKEN_ENDPOINT, { method: 'GET' })
        return response.ok && Boolean(getCookie(CSRF_COOKIE_NAME))
    } catch {
        return false
    }
}

/**
 * For where the app cannot repeat the request itself: no new token arrived, the repeated request was
 * rejected too, or the request never went through `handleFetch`. `lemonToast` keys its id off the
 * message, so a burst of rejections raises one toast rather than a stack of them.
 */
export function promptReloadForCSRF(): void {
    lemonToast.error('Requests from this tab stopped working. Reload the page to fix it.', {
        button: {
            label: 'Reload page',
            action: () => window.location.reload(),
        },
        autoClose: false,
    })
}

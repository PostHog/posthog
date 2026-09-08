import { lemonToast } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { CSRF_TOKEN_INVALID_CODE } from 'lib/api-error'
import { isOAuthMode } from 'lib/oauth/oauthClient'

export const CSRF_COOKIE_NAME = 'posthog_csrftoken'

const CSRF_TOKEN_ENDPOINT = '/api/csrf_token/'

/**
 * Whether a rejected request should be repeated with a new CSRF token. A tab open longer than its
 * cookie keeps a working session but loses its token, and only a document render used to set a new
 * one, so every request failed until the person opened a new tab. Failing that, a reload is offered,
 * because nothing else in the app can set the cookie. OAuth mode sends no CSRF token at all.
 */
export async function recoverFromCsrfRejection(response: Response, isRetry: boolean): Promise<boolean> {
    if (response.status !== 403 || isOAuthMode() || !(await isCsrfTokenRejection(response))) {
        return false
    }
    if (!isRetry && (await refreshCsrfToken())) {
        return true
    }
    promptReloadForCsrf()
    return false
}

// Reads a clone, because the caller still needs the original to build its error from.
async function isCsrfTokenRejection(response: Response): Promise<boolean> {
    try {
        const data = await response.clone().json()
        return data?.code === CSRF_TOKEN_INVALID_CODE
    } catch {
        return false
    }
}

/**
 * One in-flight refresh shared by every caller. A scene issues its requests together, so they fail
 * together, and per-request refreshes would race over which cookie every retry has to use.
 */
let inFlightRefresh: Promise<boolean> | null = null

async function refreshCsrfToken(): Promise<boolean> {
    if (!inFlightRefresh) {
        inFlightRefresh = fetchCsrfToken().finally(() => {
            inFlightRefresh = null
        })
    }
    return await inFlightRefresh
}

// A bare `fetch` rather than `api.get`, because this runs inside the failure path of every request
// and routing it back through that path would let a failing token endpoint recurse.
async function fetchCsrfToken(): Promise<boolean> {
    try {
        const response = await fetch(CSRF_TOKEN_ENDPOINT, { method: 'GET' })
        return response.ok && Boolean(getCookie(CSRF_COOKIE_NAME))
    } catch {
        return false
    }
}

let reloadPromptShown = false

function promptReloadForCsrf(): void {
    if (reloadPromptShown) {
        return
    }
    reloadPromptShown = true
    lemonToast.error('Requests from this tab stopped working. Reload the page to fix it.', {
        button: {
            label: 'Reload page',
            action: () => window.location.reload(),
        },
        autoClose: false,
    })
}

export function resetCsrfRecoveryForTests(): void {
    inFlightRefresh = null
    reloadPromptShown = false
}

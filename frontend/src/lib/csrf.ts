import { lemonToast } from '@posthog/lemon-ui'

import { getCookie } from 'lib/api'
import { CSRF_TOKEN_INVALID_CODE } from 'lib/api-error'

export const CSRF_COOKIE_NAME = 'posthog_csrftoken'

/** Reissues the CSRF cookie. GET, unauthenticated, and empty-bodied — the cookie is the payload. */
const CSRF_TOKEN_ENDPOINT = '/api/csrf_token/'

/**
 * Whether a rejected request lost its CSRF token, which is the case a new token recovers. The
 * response body has to be read to see the code, so this reads a clone: the caller still needs the
 * original to build its error from.
 */
export async function isRecoverableCsrfRejection(response: Response): Promise<boolean> {
    if (response.status !== 403) {
        return false
    }
    try {
        const data = await response.clone().json()
        return data?.code === CSRF_TOKEN_INVALID_CODE
    } catch {
        return false
    }
}

/**
 * A single in-flight refresh shared by every caller. A scene that renders several panels issues its
 * requests together, so they all fail together — the logs facet rail is the worst case, firing a
 * burst of concurrent requests per render. Without this, each one would ask for its own token, and
 * the last response to arrive would be the cookie every retry then had to use.
 */
let inFlightRefresh: Promise<boolean> | null = null

export async function refreshCsrfToken(): Promise<boolean> {
    if (!inFlightRefresh) {
        inFlightRefresh = fetchCsrfToken().finally(() => {
            inFlightRefresh = null
        })
    }
    return await inFlightRefresh
}

/**
 * Deliberately a bare `fetch` rather than `api.get`: the recovery runs from inside the failure path
 * of every request, and routing it back through that path would let a failing token endpoint
 * recurse. Same-origin by default, so the response can set the cookie.
 */
async function fetchCsrfToken(): Promise<boolean> {
    try {
        const response = await fetch(CSRF_TOKEN_ENDPOINT, { method: 'GET' })
        return response.ok && Boolean(getCookie(CSRF_COOKIE_NAME))
    } catch {
        return false
    }
}

let reloadPromptShown = false

/**
 * The last resort, for when no new token could be obtained. Everything the app can do from here
 * repeats a request with no token to send, so the retry buttons on the empty scene keep failing —
 * which is the trap this whole path exists to avoid. Only a document render sets the cookie then,
 * so say so once and let the person choose when to lose what is on screen.
 */
export function promptReloadForCsrf(): void {
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

/** Test-only: the prompt fires once per document, which would otherwise leak across test cases. */
export function resetCsrfRecoveryForTests(): void {
    inFlightRefresh = null
    reloadPromptShown = false
}

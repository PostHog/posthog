import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { asNonEmptyString, safeFetch } from '~/toolbar/utils'

import { toolbarConfigLogic } from './toolbarConfigLogic'

type OAuthTokens = { access_token: string; refresh_token: string; expires_in: number }

/** A refresh failure carrying the HTTP status, so callers can tell an expected auth-expiry apart from a real error. */
export class TokenRefreshError extends Error {
    status: number | null

    constructor(message: string, status: number | null) {
        super(message)
        this.name = 'TokenRefreshError'
        this.status = status
    }
}

// A 4xx refresh response means the refresh token is stale/expired/revoked/already rotated — a routine
// "session aged out, please re-authenticate" case the toolbar already handles with a toast. It is expected,
// not a bug, so it should not be reported to error tracking. Genuinely unexpected failures (5xx, network
// errors) still are.
function isExpectedAuthExpiry(status: number | null): boolean {
    return status !== null && status >= 400 && status < 500
}

let refreshPromise: Promise<OAuthTokens> | null = null

export async function refreshOAuthTokens(
    uiHost: string,
    clientId: string,
    currentRefreshToken: string
): Promise<OAuthTokens> {
    if (refreshPromise) {
        return refreshPromise
    }

    refreshPromise = (async () => {
        const startTime = performance.now()
        try {
            const response = await safeFetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
            })

            if (!response.ok) {
                const err = new TokenRefreshError(`Refresh failed: ${response.status}`, response.status)
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'error',
                    http_status: response.status,
                    duration_ms: Math.round(performance.now() - startTime),
                })
                // Keep the analytics event above for volume visibility, but only report genuinely
                // unexpected failures to error tracking — an expected 4xx auth-expiry is not a bug.
                if (!isExpectedAuthExpiry(response.status)) {
                    captureToolbarException(err, 'token_refresh')
                }
                throw err
            }

            const data = await response.json()
            toolbarPosthogJS.capture('toolbar token refresh', {
                status: 'success',
                duration_ms: Math.round(performance.now() - startTime),
            })
            return data
        } finally {
            refreshPromise = null
        }
    })()

    return refreshPromise
}

/**
 * Attempt a token refresh and retry on 401. Shared by toolbarFetch and toolbarUploadMedia.
 * Returns the original response if no retry is needed, or the retried response.
 */
export async function withTokenRefresh(
    response: Response,
    retryRequest: (newAccessToken: string) => Promise<Response>
): Promise<Response> {
    const logic = toolbarConfigLogic.findMounted()
    const accessToken = logic?.values.accessToken
    const refreshToken = logic?.values.refreshToken
    const clientId = logic?.values.clientId
    const uiHost = logic?.values.uiHost

    // `response?.status` (not `response.status`) so a non-Response value from a customer-page
    // `fetch` wrapper can't throw here — callers that don't route through `safeFetch` stay safe too.
    if (response?.status !== 401 || !accessToken || !refreshToken || !clientId || !uiHost) {
        return response
    }

    try {
        const tokens = await refreshOAuthTokens(uiHost, clientId, refreshToken)
        if (!toolbarConfigLogic.findMounted()) {
            return response
        }
        const access = asNonEmptyString(tokens?.access_token)
        const refresh = asNonEmptyString(tokens?.refresh_token)
        if (!access || !refresh) {
            toolbarLogger.warn('auth', 'Refresh response missing string tokens, discarding')
            // Refresh fired in response to a user action (not mount-time restore), so the
            // tokenExpired suppression by source !== 'localstorage' doesn't apply — surface
            // a toast directly so the user knows why the action failed.
            lemonToast.error('Please re-authenticate to continue using the toolbar.')
            toolbarConfigLogic.actions.tokenExpired()
            return response
        }
        toolbarConfigLogic.actions.setOAuthTokens(access, refresh, clientId)
        return await retryRequest(access)
    } catch (e) {
        toolbarLogger.error('auth', 'Token refresh retry failed', { status: response.status })
        // An expected 4xx auth-expiry is handled here with a re-authenticate toast; don't also report it
        // to error tracking (that just duplicates the noise skipped in refreshOAuthTokens).
        if (!(e instanceof TokenRefreshError && isExpectedAuthExpiry(e.status))) {
            captureToolbarException(e, 'token_refresh_retry')
        }
        lemonToast.error('Please re-authenticate to continue using the toolbar.')
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

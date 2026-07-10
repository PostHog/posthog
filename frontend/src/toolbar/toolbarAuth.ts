import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { asNonEmptyString, safeFetch } from '~/toolbar/utils'

import { toolbarConfigLogic } from './toolbarConfigLogic'

type OAuthTokens = { access_token: string; refresh_token: string; expires_in: number }

/**
 * Error thrown when an OAuth token refresh returns a non-ok response.
 *
 * A 400 is the normal outcome when a refresh token is expired, revoked, or already rotated
 * (`invalid_grant`); the backend also remaps 401/403 from the internal OAuth server down to 400.
 * The toolbar handles this by prompting the user to re-authenticate, so it's expected rather than
 * a crash worth reporting to error tracking. Only genuinely unexpected statuses (5xx and the like)
 * should be captured as exceptions.
 */
export class TokenRefreshError extends Error {
    readonly status: number
    readonly expected: boolean

    constructor(status: number) {
        super(`Refresh failed: ${status}`)
        this.name = 'TokenRefreshError'
        this.status = status
        this.expected = status === 400
    }
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
                const err = new TokenRefreshError(response.status)
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'error',
                    http_status: response.status,
                    duration_ms: Math.round(performance.now() - startTime),
                })
                // Skip the expected auth-expiry case (a 400 invalid_grant) so it doesn't
                // clutter error tracking; the toolbar still prompts the user to re-auth.
                if (!err.expected) {
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
        // A 400 refresh failure is the expected "session expired" path, not a crash: skip
        // capturing it so error tracking only surfaces genuinely unexpected failures.
        if (!(e instanceof TokenRefreshError) || !e.expected) {
            captureToolbarException(e, 'token_refresh_retry')
        }
        lemonToast.error('Please re-authenticate to continue using the toolbar.')
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

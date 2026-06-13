import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { asNonEmptyString } from '~/toolbar/utils'

import { toolbarConfigLogic } from './toolbarConfigLogic'

type OAuthTokens = { access_token: string; refresh_token: string; expires_in: number }

/**
 * Thrown when the refresh endpoint responds with a non-2xx status. Carries the
 * HTTP status so callers can tell ordinary token expiry (4xx — the backend
 * remaps the OAuth server's 401/403 to 400) apart from genuinely unexpected
 * server failures (5xx).
 */
export class TokenRefreshError extends Error {
    constructor(public readonly status: number) {
        super(`Refresh failed: ${status}`)
        this.name = 'TokenRefreshError'
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
            const response = await fetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
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
                // A 4xx means the refresh token is simply expired/revoked — an
                // expected condition that withTokenRefresh handles with a re-auth
                // toast. Don't report it as a hard exception (it floods error
                // tracking and drowns out real toolbar bugs); just warn. Only 5xx
                // is genuinely unexpected and worth capturing.
                if (response.status >= 500) {
                    captureToolbarException(err, 'token_refresh')
                } else {
                    toolbarLogger.warn('auth', 'Token refresh rejected, re-authentication required', {
                        status: response.status,
                    })
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

    if (response.status !== 401 || !accessToken || !refreshToken || !clientId || !uiHost) {
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
        toolbarLogger.warn('auth', 'Token refresh retry failed', { status: response.status })
        // refreshOAuthTokens already decided whether its own rejection warrants an
        // exception (5xx only). Anything else reaching here — network or parse
        // failures — is genuinely unexpected, so capture it.
        if (!(e instanceof TokenRefreshError)) {
            captureToolbarException(e, 'token_refresh_retry')
        }
        lemonToast.error('Please re-authenticate to continue using the toolbar.')
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

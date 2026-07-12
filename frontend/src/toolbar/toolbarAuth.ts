import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { ToolbarRequestError } from '~/toolbar/toolbarRequestError'
import { asNonEmptyString, safeFetch } from '~/toolbar/utils'

import { toolbarConfigLogic } from './toolbarConfigLogic'

type OAuthTokens = { access_token: string; refresh_token: string; expires_in: number }

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
            // Every failure below is an expected request outcome (expired/revoked refresh
            // token, network hiccup, proxy error page) - tracked via the capture event and
            // logs, never reported to error tracking.
            let response: Response
            try {
                response = await safeFetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
                })
            } catch {
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'network_error',
                    duration_ms: Math.round(performance.now() - startTime),
                })
                throw new ToolbarRequestError('Refresh failed: network error')
            }

            if (!response.ok) {
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'error',
                    http_status: response.status,
                    duration_ms: Math.round(performance.now() - startTime),
                })
                throw new ToolbarRequestError(`Refresh failed: ${response.status}`, response.status)
            }

            let data: OAuthTokens
            try {
                data = await response.json()
            } catch {
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'invalid_response',
                    http_status: response.status,
                    duration_ms: Math.round(performance.now() - startTime),
                })
                throw new ToolbarRequestError('Refresh failed: malformed response', response.status)
            }
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
        try {
            return await retryRequest(access)
        } catch {
            // The refresh succeeded but the replayed request failed at the network level -
            // an expected request outcome. Hand back the original 401 so callers treat it
            // as an ordinary failed response instead of an exception.
            toolbarLogger.warn('auth', 'Request replay after token refresh failed at network level')
            return response
        }
    } catch (e) {
        toolbarLogger.error('auth', 'Token refresh retry failed', { status: response.status })
        // Failed refreshes are expected request outcomes (ToolbarRequestError) - only a
        // genuine bug in the refresh/retry code itself is worth an exception.
        if (!(e instanceof ToolbarRequestError)) {
            captureToolbarException(e, 'token_refresh_retry')
        }
        lemonToast.error('Please re-authenticate to continue using the toolbar.')
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

import { toolbarLogger } from '~/toolbar/core/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/core/toolbarPosthogJS'

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
            const response = await fetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
            })

            if (!response.ok) {
                const err = new Error(`Refresh failed: ${response.status}`)
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'error',
                    http_status: response.status,
                    duration_ms: Math.round(performance.now() - startTime),
                })
                captureToolbarException(err, 'token_refresh')
                throw err
            }

            toolbarPosthogJS.capture('toolbar token refresh', {
                status: 'success',
                duration_ms: Math.round(performance.now() - startTime),
            })
            return await response.json()
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
        toolbarConfigLogic.actions.setOAuthTokens(tokens.access_token, tokens.refresh_token, clientId)
        return await retryRequest(tokens.access_token)
    } catch (e) {
        toolbarLogger.error('auth', 'Token refresh retry failed', { status: response.status })
        captureToolbarException(e, 'token_refresh_retry')
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

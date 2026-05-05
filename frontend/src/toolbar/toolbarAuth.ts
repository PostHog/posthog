import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'

import { toolbarConfigLogic } from './toolbarConfigLogic'

type OAuthTokens = { access_token: string; refresh_token: string; expires_in: number }

// Marker base class for errors thrown by `refreshOAuthTokens`. Both subclasses are reported
// to analytics inside the function, so `withTokenRefresh` skips its own capture for these.
class RefreshError extends Error {}

class RefreshHTTPError extends RefreshError {
    constructor(public readonly status: number) {
        super(`Refresh failed: ${status}`)
        this.name = 'RefreshHTTPError'
    }
}

class RefreshNetworkError extends RefreshError {
    constructor(cause: unknown) {
        super(`Refresh network error: ${cause instanceof Error ? cause.message : String(cause)}`)
        this.name = 'RefreshNetworkError'
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
            let response: Response
            try {
                response = await fetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
                })
            } catch (cause) {
                // Browser-level fetch failures (offline, navigation, ad blocker, CORS) surface as
                // `TypeError: Failed to fetch`. Capture as a typed event only — these are transient
                // and shouldn't pollute exception tracking with an untyped TypeError fingerprint.
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'network_error',
                    duration_ms: Math.round(performance.now() - startTime),
                })
                throw new RefreshNetworkError(cause)
            }

            if (!response.ok) {
                const err = new RefreshHTTPError(response.status)
                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'error',
                    http_status: response.status,
                    duration_ms: Math.round(performance.now() - startTime),
                })
                captureToolbarException(err, 'token_refresh')
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
        toolbarConfigLogic.actions.setOAuthTokens(tokens.access_token, tokens.refresh_token, clientId)
        return await retryRequest(tokens.access_token)
    } catch (e) {
        toolbarLogger.error('auth', 'Token refresh retry failed', { status: response.status })
        // `refreshOAuthTokens` already reports its own failure paths; avoid double-capturing.
        if (!(e instanceof RefreshError)) {
            captureToolbarException(e, 'token_refresh_retry')
        }
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

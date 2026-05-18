import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'

import { toolbarConfigLogic } from './toolbarConfigLogic'

type OAuthTokens = { access_token: string; refresh_token: string; expires_in: number }

class RefreshError extends Error {
    httpStatus: number
    oauthError?: string

    constructor(message: string, httpStatus: number, oauthError?: string) {
        super(message)
        this.httpStatus = httpStatus
        this.oauthError = oauthError
    }
}

function isTerminalRefreshError(err: unknown): boolean {
    if (!(err instanceof RefreshError)) {
        return false
    }
    if (err.oauthError === 'invalid_grant' || err.oauthError === 'invalid_token') {
        return true
    }
    if (err.httpStatus >= 400 && err.httpStatus < 500 && err.httpStatus !== 408 && err.httpStatus !== 429) {
        return true
    }
    return false
}

const RETRY_BACKOFF_MS = 400

let refreshPromise: Promise<OAuthTokens> | null = null

async function attemptRefresh(uiHost: string, clientId: string, currentRefreshToken: string): Promise<OAuthTokens> {
    const startTime = performance.now()
    let response: Response
    try {
        response = await fetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
        })
    } catch (networkErr) {
        toolbarPosthogJS.capture('toolbar token refresh', {
            status: 'network_error',
            duration_ms: Math.round(performance.now() - startTime),
        })
        throw new RefreshError(networkErr instanceof Error ? networkErr.message : 'network error', 0)
    }

    if (!response.ok) {
        let oauthError: string | undefined
        try {
            const body = await response.json()
            if (body && typeof body.error === 'string') {
                oauthError = body.error
            }
        } catch {
            // not JSON
        }
        toolbarPosthogJS.capture('toolbar token refresh', {
            status: 'error',
            http_status: response.status,
            oauth_error: oauthError,
            duration_ms: Math.round(performance.now() - startTime),
        })
        throw new RefreshError(`Refresh failed: ${response.status}`, response.status, oauthError)
    }

    const data: OAuthTokens = await response.json()
    toolbarPosthogJS.capture('toolbar token refresh', {
        status: 'success',
        duration_ms: Math.round(performance.now() - startTime),
    })
    return data
}

export async function refreshOAuthTokens(
    uiHost: string,
    clientId: string,
    currentRefreshToken: string
): Promise<OAuthTokens> {
    if (refreshPromise) {
        return refreshPromise
    }

    refreshPromise = (async () => {
        try {
            try {
                return await attemptRefresh(uiHost, clientId, currentRefreshToken)
            } catch (err) {
                if (isTerminalRefreshError(err)) {
                    throw err
                }
                toolbarLogger.warn('auth', 'Transient refresh failure, retrying once')
                await new Promise((resolve) => setTimeout(resolve, RETRY_BACKOFF_MS))
                return await attemptRefresh(uiHost, clientId, currentRefreshToken)
            }
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
        const terminal = isTerminalRefreshError(e)
        toolbarLogger.error('auth', 'Token refresh retry failed', {
            status: response.status,
            terminal,
        })
        captureToolbarException(e, 'token_refresh_retry', { terminal })
        if (terminal) {
            toolbarConfigLogic.actions.tokenExpired()
        }
        return response
    }
}

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { toolbarLogger } from '~/toolbar/toolbarLogger'
import { captureToolbarException, toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { asNonEmptyString } from '~/toolbar/utils'

import { toolbarConfigLogic } from './toolbarConfigLogic'

type OAuthTokens = { access_token: string; refresh_token: string; expires_in: number }

// The refresh endpoint itself only ever returns 400/401/500/502 (see ToolbarOAuthRefreshView).
// A 408 (and other 5xx/429) therefore reflects an upstream timeout or momentary gateway blip — a
// transient condition we retry rather than surfacing as an error-tracking exception. Network
// failures (fetch rejecting) are treated the same way.
const TRANSIENT_REFRESH_STATUSES = new Set([408, 425, 429, 500, 502, 503, 504])
const MAX_REFRESH_ATTEMPTS = 2

/**
 * Error thrown when an OAuth token refresh fails. `transient` flags gateway/network blips that
 * aren't actionable auth failures, so callers can skip exception capture for them.
 */
export class ToolbarRefreshError extends Error {
    status: number
    transient: boolean

    constructor(status: number, transient: boolean) {
        super(`Refresh failed: ${status}`)
        this.name = 'ToolbarRefreshError'
        this.status = status
        this.transient = transient
    }
}

export function isTransientRefreshError(error: unknown): boolean {
    return error instanceof ToolbarRefreshError && error.transient
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
            for (let attempt = 1; attempt <= MAX_REFRESH_ATTEMPTS; attempt++) {
                let response: Response
                try {
                    response = await fetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
                    })
                } catch {
                    // fetch only rejects on a network failure, which is always transient.
                    if (attempt < MAX_REFRESH_ATTEMPTS) {
                        continue
                    }
                    toolbarPosthogJS.capture('toolbar token refresh', {
                        status: 'error',
                        http_status: 0,
                        transient: true,
                        attempts: attempt,
                        duration_ms: Math.round(performance.now() - startTime),
                    })
                    throw new ToolbarRefreshError(0, true)
                }

                if (response.ok) {
                    const data = await response.json()
                    toolbarPosthogJS.capture('toolbar token refresh', {
                        status: 'success',
                        attempts: attempt,
                        duration_ms: Math.round(performance.now() - startTime),
                    })
                    return data
                }

                const transient = TRANSIENT_REFRESH_STATUSES.has(response.status)
                if (transient && attempt < MAX_REFRESH_ATTEMPTS) {
                    continue
                }

                toolbarPosthogJS.capture('toolbar token refresh', {
                    status: 'error',
                    http_status: response.status,
                    transient,
                    attempts: attempt,
                    duration_ms: Math.round(performance.now() - startTime),
                })
                const err = new ToolbarRefreshError(response.status, transient)
                // Transient gateway/network conditions (e.g. a momentary 408) aren't actionable
                // auth failures — keep the analytics event for visibility but don't create
                // error-tracking issues for them.
                if (!transient) {
                    captureToolbarException(err, 'token_refresh')
                }
                throw err
            }
            // Unreachable: the loop returns on success or throws on the final attempt.
            throw new ToolbarRefreshError(0, true)
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
        const transient = isTransientRefreshError(e)
        // Transient gateway/network blips aren't actionable auth failures — log at warn level and
        // skip exception capture so they don't create error-tracking issues.
        if (transient) {
            toolbarLogger.warn('auth', 'Token refresh retry failed (transient)', { status: response.status })
        } else {
            toolbarLogger.error('auth', 'Token refresh retry failed', { status: response.status })
            captureToolbarException(e, 'token_refresh_retry')
        }
        lemonToast.error('Please re-authenticate to continue using the toolbar.')
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

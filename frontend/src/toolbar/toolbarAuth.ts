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
        try {
            const response = await fetch(`${uiHost}/api/user/toolbar_oauth_refresh/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ refresh_token: currentRefreshToken, client_id: clientId }),
            })

            if (!response.ok) {
                throw new Error(`Refresh failed: ${response.status}`)
            }

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
    } catch {
        toolbarConfigLogic.actions.tokenExpired()
        return response
    }
}

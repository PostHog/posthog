import { generatePKCE, parseToolbarAuthHash, requestOAuthTokens } from '~/toolbar/shared/utils'

import type { PageToolbarTokens } from '../messaging/pageToolbarBridge'
import { waitForTabUrl } from './extensionBrowser'

// A background tab normally redirects back within a few seconds. A tab the user watches can stop on a login or
// consent page, so it gets longer.
const BACKGROUND_AUTH_TIMEOUT_MS = 20_000
const INTERACTIVE_AUTH_TIMEOUT_MS = 180_000

class OAuthExchangeError extends Error {}

function pageUrlWithoutHash(pageUrl: string): string {
    const url = new URL(pageUrl)
    url.hash = ''
    return url.toString()
}

/**
 * Runs the floating toolbar's OAuth flow in a separate tab. PostHog redirects that tab to the page with the code in the
 * URL hash, so the page must be one of the project's authorized URLs. The extension keeps the PKCE verifier, reads the
 * code from the tab's URL, and exchanges it for tokens.
 */
export async function authenticateToolbar({
    uiHost,
    pageUrl,
    interactive,
}: {
    uiHost: string
    pageUrl: string
    interactive: boolean
}): Promise<PageToolbarTokens> {
    const { verifier, challenge } = await generatePKCE()
    const authorizeUrl = `${uiHost}/toolbar_oauth/authorize/?${new URLSearchParams({
        redirect: pageUrlWithoutHash(pageUrl),
        code_challenge: challenge,
    })}`
    const callbackUrl = await waitForTabUrl(authorizeUrl, (url) => !!parseToolbarAuthHash(new URL(url).hash), {
        active: interactive,
        timeoutMs: interactive ? INTERACTIVE_AUTH_TIMEOUT_MS : BACKGROUND_AUTH_TIMEOUT_MS,
    })
    const authParams = parseToolbarAuthHash(new URL(callbackUrl).hash)
    if (!authParams) {
        throw new OAuthExchangeError('PostHog returned no authorization code')
    }

    const { status, accessToken, refreshToken } = await requestOAuthTokens({
        uiHost,
        code: authParams.code,
        clientId: authParams.clientId,
        verifier,
    })
    if (!accessToken) {
        throw new OAuthExchangeError(`The token exchange failed with status ${status}`)
    }
    return { accessToken, refreshToken, clientId: authParams.clientId }
}

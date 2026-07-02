import { actions, kea, listeners, path, reducers } from 'kea'
import { urlToAction } from 'kea-router'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { getRelativeNextPath } from 'lib/utils/url'

import { Region } from '~/types'

import { buildAuthorizeUrl, clearSession, exchangeCodeForToken, OAUTH_REGIONS, PendingAuth } from './oauthClient'
import type { oauthLogicType } from './oauthLogicType'
import { generateCodeVerifier, generateState } from './pkce'

export const oauthLogic = kea<oauthLogicType>([
    path(['lib', 'oauth', 'oauthLogic']),
    actions({
        beginLogin: (region: Region.US | Region.EU) => ({ region }),
        handleCallback: (code: string, state: string) => ({ code, state }),
        logout: true,
        setLoginError: (error: string | null) => ({ error }),
        setPendingAuth: (pending: PendingAuth) => ({ pending }),
        clearPendingAuth: true,
    }),
    reducers({
        // Persisted to survive the redirect out to the provider and back.
        pendingAuth: [
            null as PendingAuth | null,
            { persist: true },
            {
                setPendingAuth: (_, { pending }) => pending,
                clearPendingAuth: () => null,
            },
        ],
        loginError: [
            null as string | null,
            {
                setLoginError: (_, { error }) => error,
                beginLogin: () => null,
                handleCallback: () => null,
            },
        ],
        loginInProgress: [
            false,
            {
                beginLogin: () => true,
                handleCallback: () => true,
                setLoginError: () => false,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        beginLogin: async ({ region }) => {
            const config = OAUTH_REGIONS[region]
            const pending: PendingAuth = {
                backendHost: config.host,
                clientId: config.clientId,
                codeVerifier: generateCodeVerifier(),
                state: generateState(),
                returnTo: getRelativeNextPath(new URLSearchParams(window.location.search).get('next'), location) || '/',
            }
            actions.setPendingAuth(pending)
            // the authorize URL targets the hardcoded OAUTH_REGIONS host, not user input
            // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
            window.location.href = await buildAuthorizeUrl(pending)
        },
        handleCallback: async ({ code, state }) => {
            const { pendingAuth } = values
            if (!pendingAuth) {
                actions.setLoginError('No pending OAuth flow found. Please start the login again.')
                return
            }
            try {
                await exchangeCodeForToken(pendingAuth, code, state)
                actions.clearPendingAuth()
                // Full navigation so the app re-bootstraps against the remote region with the new token.
                // nosemgrep: javascript.browser.security.open-redirect.js-open-redirect
                window.location.href = pendingAuth.returnTo || '/'
            } catch (error) {
                const message = error instanceof Error ? error.message : 'OAuth login failed.'
                actions.setLoginError(message)
                lemonToast.error(message)
            }
        },
        logout: () => {
            clearSession()
            // Back to the local instance's login.
            window.location.href = '/login'
        },
    })),
    urlToAction(({ actions }) => ({
        '/oauth/callback': (_, searchParams) => {
            if (searchParams.error) {
                actions.setLoginError(`OAuth error: ${searchParams.error_description || searchParams.error}`)
                return
            }
            if (searchParams.code) {
                actions.handleCallback(searchParams.code, searchParams.state)
            } else if (!searchParams.error) {
                actions.setLoginError('No authorization code received. Please start the login again.')
            }
        },
    })),
])

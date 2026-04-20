import { actions, events, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { linkedAccountsLogicType } from './linkedAccountsLogicType'

export type LinkedAccountConnectFlow = 'github_link' | 'social_login'

export interface LinkedAccount {
    provider: string
    display_name: string
    connected: boolean
    account_identifier: string | null
    login_enabled: boolean | null
    can_enable_login: boolean
    can_disconnect: boolean
    created_at: string | null
    modified_at: string | null
    connect_flow: LinkedAccountConnectFlow | null
    connect_path: string | null
}

interface LinkedAccountsResponse {
    results: LinkedAccount[]
    sso_enforcement: string | null
    sso_enforcement_provider_name: string | null
}

interface GithubStartResponse {
    authorize_url: string
}

/** Key for stashing the ``connect_from`` URL param across the GitHub OAuth roundtrip.
 *
 * The link flow leaves posthog.com for github.com and comes back, which drops the query
 * string that brought the user here. sessionStorage survives the roundtrip because it's
 * scoped to the tab, not the navigation. */
const CONNECT_FROM_STORAGE_KEY = 'linked_accounts_connect_from'

function readConnectFromStorage(): string | null {
    try {
        return sessionStorage.getItem(CONNECT_FROM_STORAGE_KEY)
    } catch {
        return null
    }
}

function writeConnectFromStorage(value: string | null): void {
    try {
        if (value) {
            sessionStorage.setItem(CONNECT_FROM_STORAGE_KEY, value)
        } else {
            sessionStorage.removeItem(CONNECT_FROM_STORAGE_KEY)
        }
    } catch {
        // No-op: private-browsing or storage-disabled sessions just lose the CTA hint.
    }
}

export const linkedAccountsLogic = kea<linkedAccountsLogicType>([
    path(['scenes', 'settings', 'user', 'linkedAccountsLogic']),

    actions({
        setLoginEnabled: (provider: string, loginEnabled: boolean) => ({ provider, loginEnabled }),
        disconnect: (provider: string, displayName: string) => ({ provider, displayName }),
        connect: (account: LinkedAccount) => ({ account }),
        setSsoEnforcementProvider: (providerName: string | null) => ({ providerName }),
    }),

    reducers({
        ssoEnforcementProviderName: [
            null as string | null,
            {
                setSsoEnforcementProvider: (_, { providerName }) => providerName,
            },
        ],
    }),

    loaders(({ values, actions }) => ({
        linkedAccounts: [
            [] as LinkedAccount[],
            {
                loadLinkedAccounts: async () => {
                    const response = await api.get<LinkedAccountsResponse>('api/users/@me/linked_accounts/')
                    actions.setSsoEnforcementProvider(response.sso_enforcement_provider_name)
                    return response.results
                },
                setLoginEnabled: async ({ provider, loginEnabled }) => {
                    const updated = await api.update<LinkedAccount>(`api/users/@me/linked_accounts/${provider}/`, {
                        login_enabled: loginEnabled,
                    })
                    return values.linkedAccounts.map((a) => (a.provider === provider ? updated : a))
                },
                disconnect: async ({ provider, displayName }) => {
                    // The DELETE endpoint returns the refreshed list so we don't need a follow-up GET.
                    const response: Response = await api.delete(`api/users/@me/linked_accounts/${provider}/`)
                    const body = (await response.json()) as LinkedAccountsResponse
                    actions.setSsoEnforcementProvider(body.sso_enforcement_provider_name)
                    lemonToast.success(`Disconnected ${displayName}`)
                    return body.results
                },
            },
        ],
    })),

    listeners(() => ({
        connect: async ({ account }) => {
            if (!account.connect_path) {
                return
            }
            if (account.connect_flow === 'github_link') {
                try {
                    const response = await api.create<GithubStartResponse>(account.connect_path, {})
                    window.location.href = response.authorize_url
                } catch (error: any) {
                    lemonToast.error(error?.detail || 'Could not start GitHub linking.')
                }
                return
            }
            if (account.connect_flow === 'social_login') {
                window.location.href = account.connect_path
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadLinkedAccounts()
            const params = new URLSearchParams(window.location.search)

            // Stash ``connect_from`` so the post-roundtrip success toast can surface a
            // "Return to PostHog Code" CTA. Stored before any early returns so we also
            // capture it when the user arrives here from the app but hasn't clicked yet.
            const connectFrom = params.get('connect_from')
            if (connectFrom) {
                writeConnectFromStorage(connectFrom)
            }

            if (params.has('github_link_success')) {
                const origin = readConnectFromStorage()
                writeConnectFromStorage(null)
                if (origin === 'posthog_code') {
                    lemonToast.success('GitHub account linked. You can return to PostHog Code.', {
                        autoClose: false,
                        button: {
                            label: 'Return to PostHog Code',
                            action: () => {
                                window.location.href = 'posthog-code://github-linked'
                            },
                        },
                    })
                } else {
                    lemonToast.success('GitHub account linked.')
                }
            } else if (params.has('github_link_error')) {
                writeConnectFromStorage(null)
                const reason = params.get('github_link_error')
                const message =
                    reason === 'already_linked'
                        ? 'That GitHub account is already linked to another PostHog account.'
                        : reason === 'would_disable_only_login'
                          ? 'Linking a different GitHub account would lock you out. Set a password or link another sign-in method first.'
                          : reason === 'access_denied'
                            ? 'GitHub authorization was canceled.'
                            : reason === 'github_oauth_error'
                              ? 'GitHub rejected the authorization. Please try again.'
                              : reason === 'missing_params'
                                ? "GitHub didn't send back the expected parameters. Please try again."
                                : reason === 'invalid_state'
                                  ? 'The GitHub link request expired or could not be verified. Please try again.'
                                  : reason === 'exchange_failed'
                                    ? 'GitHub rejected the authorization code. Check that GITHUB_APP_CLIENT_ID and GITHUB_APP_OAUTH_CLIENT_SECRET are configured correctly (server logs have the specific reason).'
                                    : 'Could not link GitHub account. Please try again.'
                lemonToast.error(message)
            }
        },
    })),
])

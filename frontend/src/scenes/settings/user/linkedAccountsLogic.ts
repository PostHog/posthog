import { actions, events, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'

import type { linkedAccountsLogicType } from './linkedAccountsLogicType'

export interface LinkedAccount {
    kind: string
    connected: boolean
    account_identifier: string | null
    installation_id: string | null
    repository_selection: string | null
    account: { type: string; name: string } | null
    created_at: string | null
}

interface LinkedAccountsResponse {
    results: LinkedAccount[]
}

interface GithubStartResponse {
    install_url: string
}

/** Key for stashing the ``connect_from`` URL param across the GitHub install roundtrip.
 *
 * The install flow leaves posthog.com for github.com and comes back, which drops the query
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
        disconnectGitHub: true,
        connectGitHub: true,
    }),

    loaders(() => ({
        linkedAccounts: [
            [] as LinkedAccount[],
            {
                loadLinkedAccounts: async () => {
                    const response = await api.get<LinkedAccountsResponse>('api/users/@me/linked_accounts/')
                    return response.results
                },
                disconnectGitHub: async () => {
                    const response: Response = await api.delete('api/users/@me/linked_accounts/github/')
                    const body = (await response.json()) as LinkedAccountsResponse
                    lemonToast.success('Disconnected GitHub')
                    return body.results
                },
            },
        ],
    })),

    listeners(() => ({
        connectGitHub: async () => {
            try {
                const response = await api.create<GithubStartResponse>(
                    'api/users/@me/linked_accounts/github/start/',
                    {}
                )
                window.location.href = response.install_url
            } catch (error: any) {
                lemonToast.error(error?.detail || 'Could not start GitHub installation.')
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadLinkedAccounts()
            const params = new URLSearchParams(window.location.search)

            // Stash ``connect_from`` so the post-roundtrip success toast can surface a
            // "Return to PostHog Code" CTA.
            const connectFrom = params.get('connect_from')
            if (connectFrom) {
                writeConnectFromStorage(connectFrom)
            }

            if (params.has('github_link_success')) {
                const origin = readConnectFromStorage()
                writeConnectFromStorage(null)
                if (origin === 'posthog_code') {
                    lemonToast.success('GitHub connected. You can return to PostHog Code.', {
                        autoClose: false,
                        button: {
                            label: 'Return to PostHog Code',
                            action: () => {
                                window.location.href = 'posthog-code://github-linked'
                            },
                        },
                    })
                } else {
                    lemonToast.success('GitHub connected.')
                }
            } else if (params.has('github_link_error')) {
                writeConnectFromStorage(null)
                const reason = params.get('github_link_error')
                const message =
                    reason === 'access_denied'
                        ? 'GitHub authorization was canceled.'
                        : reason === 'github_oauth_error'
                          ? 'GitHub rejected the authorization. Please try again.'
                          : reason === 'missing_params'
                            ? "GitHub didn't send back the expected parameters. Please try again."
                            : reason === 'invalid_state'
                              ? 'The GitHub link request expired or could not be verified. Please try again.'
                              : reason === 'exchange_failed'
                                ? 'GitHub rejected the authorization code. Check that the GitHub App is configured correctly.'
                                : reason === 'installation_fetch_failed'
                                  ? 'Could not fetch installation details from GitHub. Please try again.'
                                  : reason === 'installation_token_failed'
                                    ? 'Could not get an installation token from GitHub. Please try again.'
                                    : 'Could not connect GitHub. Please try again.'
                lemonToast.error(message)
            }
        },
    })),
])

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
            if (params.has('github_link_success')) {
                lemonToast.success('GitHub account linked.')
            } else if (params.has('github_link_error')) {
                const reason = params.get('github_link_error')
                const message =
                    reason === 'already_linked'
                        ? 'That GitHub account is already linked to another PostHog account.'
                        : reason === 'would_disable_only_login'
                          ? 'Linking a different GitHub account would lock you out. Set a password or link another sign-in method first.'
                          : 'Could not link GitHub account. Please try again.'
                lemonToast.error(message)
            }
        },
    })),
])

import { actions, connect, events, kea, listeners, path } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import type { personalIntegrationsLogicType } from './personalIntegrationsLogicType'

export interface PersonalGitHubIntegration {
    kind: string
    installation_id: string | null
    repository_selection: string | null
    account: { type: string; name: string } | null
    uses_shared_installation: boolean
    created_at: string | null
}

interface GithubStartResponse {
    install_url: string
}

/** Key for stashing the ``connect_from`` URL param across the GitHub install roundtrip.
 *
 * The install flow leaves posthog.com for github.com and comes back, which drops the query
 * string that brought the user here. sessionStorage survives the roundtrip because it's
 * scoped to the tab, not the navigation. */
const CONNECT_FROM_STORAGE_KEY = 'personal_integrations_connect_from'

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
        console.warn('Failed to write connect_from value for account linking redirect, skipping', value)
    }
}

export const personalIntegrationsLogic = kea<personalIntegrationsLogicType>([
    path(['scenes', 'settings', 'user', 'personalIntegrationsLogic']),

    connect(() => ({
        actions: [
            integrationsLogic,
            ['loadIntegrations as loadProjectIntegrations', 'loadIntegrationsSuccess as projectIntegrationsLoaded'],
        ],
    })),

    actions({
        connectGitHub: true,
        disconnectGitHub: (installationId: string) => ({ installationId }),
    }),

    loaders(() => ({
        integrations: [
            [] as PersonalGitHubIntegration[],
            {
                loadIntegrations: async () => {
                    const response = await api.get<{ results: PersonalGitHubIntegration[] }>(
                        'api/users/@me/integrations/'
                    )
                    return response.results
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        projectIntegrationsLoaded: () => {
            // When a project-level integration is added/removed, the backend may
            // auto-create a user-level integration. Reload to pick it up.
            actions.loadIntegrations()
        },
        connectGitHub: async () => {
            try {
                const connectFrom = readConnectFromStorage()
                const body = connectFrom === 'posthog_code' ? { connect_from: 'posthog_code' as const } : {}
                const response = await api.create<GithubStartResponse>('api/users/@me/integrations/github/start/', body)
                window.location.href = response.install_url
            } catch (error: unknown) {
                const message = error instanceof Error && 'detail' in error ? (error as any).detail : undefined
                lemonToast.error(message || 'Could not start GitHub installation.')
            }
        },
        disconnectGitHub: async ({ installationId }) => {
            try {
                await api.delete(`api/users/@me/integrations/github/${installationId}/`)
                lemonToast.success('Disconnected GitHub installation')
                actions.loadIntegrations()
                actions.loadProjectIntegrations()
            } catch {
                lemonToast.error('Could not disconnect GitHub installation.')
            }
        },
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadIntegrations()
            const params = new URLSearchParams(window.location.search)

            // Stash ``connect_from`` so the post-roundtrip success toast can surface a
            // "Return to PostHog Code" CTA.
            const connectFrom = params.get('connect_from')
            if (connectFrom) {
                writeConnectFromStorage(connectFrom)
            }

            if (params.has('github_link_success')) {
                writeConnectFromStorage(null)
                lemonToast.success('GitHub connected.')
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

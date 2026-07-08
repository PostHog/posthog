import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { describeGithubLinkError } from 'lib/integrations/githubSetupErrors'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    usersIntegrationsGithubDestroy,
    usersIntegrationsGithubStartCreate,
    usersIntegrationsSlackDestroy,
    usersIntegrationsSlackLinkableWorkspacesRetrieve,
    usersIntegrationsSlackStartCreate,
} from '~/generated/core/api'

import type { personalIntegrationsLogicType } from './personalIntegrationsLogicType'

export interface PersonalGitHubIntegration {
    kind: 'github'
    installation_id: string | null
    repository_selection: string | null
    account: { type: string; name: string } | null
    uses_shared_installation: boolean
    created_at: string | null
}

export interface PersonalSlackIntegration {
    id: string
    kind: 'slack'
    slack_user_id: string
    slack_team_id: string
    slack_team_name: string | null
    slack_email_at_link: string | null
    created_at: string | null
}

export interface LinkableSlackWorkspace {
    posthog_team_id: number
    posthog_team_name: string
    posthog_organization_name: string
    slack_team_id: string
    slack_team_name: string | null
}

const SLACK_LINK_ERROR_MESSAGES: Record<string, string> = {
    access_denied: 'Slack authorization was canceled.',
    invalid_state: 'The Slack link request expired or could not be verified. Please try again.',
    workspace_not_found: 'The Slack workspace is no longer connected to PostHog.',
    flag_off: "Slack identity linking isn't enabled for this organization.",
    exchange_failed: 'Slack rejected the authorization. Please try again.',
    team_mismatch: 'You signed in to a different Slack workspace than the one that started this flow.',
    org_mismatch: "You aren't a member of the PostHog organization connected to this Slack workspace.",
    session_mismatch:
        'This Slack link was started in a different PostHog session. Please start the link again from settings.',
    not_configured: 'Slack is not configured for this PostHog instance.',
}
const SLACK_LINK_ERROR_FALLBACK = 'Could not connect Slack. Please try again.'

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
        values: [teamLogic, ['currentTeam'], featureFlagLogic, ['featureFlags']],
        actions: [
            integrationsLogic,
            ['loadIntegrations as loadProjectIntegrations', 'loadIntegrationsSuccess as projectIntegrationsLoaded'],
        ],
    })),

    actions({
        connectGitHub: true,
        connectGitHubFailure: true,
        disconnectGitHub: (installationId: string) => ({ installationId }),
        disconnectSlack: (slackUserId: string) => ({ slackUserId }),
    }),

    reducers({
        // Guards against double-submission: the install request redirects to github.com on success
        // (so it never needs resetting then), and resets on failure so the user can retry.
        githubConnecting: [
            false,
            {
                connectGitHub: () => true,
                connectGitHubFailure: () => false,
            },
        ],
    }),

    loaders(() => ({
        integrations: [
            [] as PersonalGitHubIntegration[],
            {
                loadIntegrations: async () => {
                    // The list endpoint returns a flat `{results: [...]}` payload,
                    // but drf-spectacular auto-wraps `list()` viewset methods in a
                    // paginated schema, so the generated helper would mis-type the
                    // response — call `api.get` directly until the backend serializer
                    // is decorated to bypass pagination.
                    const response = await api.get<{ results: PersonalGitHubIntegration[] }>(
                        'api/users/@me/integrations/'
                    )
                    return response.results
                },
            },
        ],
        slackIntegrations: [
            [] as PersonalSlackIntegration[],
            {
                loadSlackIntegrations: async () => {
                    const response = await api.get<{ results: PersonalSlackIntegration[] }>(
                        'api/users/@me/integrations/?kind=slack'
                    )
                    return response.results
                },
            },
        ],
        linkableSlackWorkspaces: [
            [] as LinkableSlackWorkspace[],
            {
                loadLinkableSlackWorkspaces: async () => {
                    const response = await usersIntegrationsSlackLinkableWorkspacesRetrieve('@me')
                    return response.results as LinkableSlackWorkspace[]
                },
            },
        ],
        slackConnect: [
            false as boolean,
            {
                connectSlack: async (payload: { workspace?: LinkableSlackWorkspace } = {}) => {
                    try {
                        const body = payload.workspace
                            ? {
                                  team_id: payload.workspace.posthog_team_id,
                                  slack_team_id: payload.workspace.slack_team_id,
                              }
                            : {}
                        const response = await usersIntegrationsSlackStartCreate('@me', body)
                        window.location.href = response.install_url
                        return true
                    } catch (error: unknown) {
                        // DRF errors come through as ApiError with `.detail` (string|null),
                        // `.data` (the parsed body — often `{detail: '…'}` or an array of strings),
                        // and `.message`. Read `detail` first, then fall back to `data.detail`
                        // / first array entry, then the error message itself. Without this, a
                        // ValidationError like "You're already linked to this Slack workspace."
                        // surfaces only as the generic fallback because `detail` is null on
                        // non-`detail`-shaped DRF bodies.
                        const message =
                            error instanceof Error
                                ? (error as any).detail ||
                                  (error as any).data?.detail ||
                                  (Array.isArray((error as any).data) ? (error as any).data[0] : undefined) ||
                                  error.message
                                : undefined
                        lemonToast.error(message || 'Could not start Slack linking.')
                        return false
                    }
                },
            },
        ],
    })),

    selectors({
        // Gating selector for the new section. Read once in the component so the
        // backend endpoints are still queryable for users who linked before the
        // flag flipped off — only the *new connect / discoverability* surface
        // is hidden, not the unlink path.
        slackLinkEnabled: [
            (s) => [s.featureFlags],
            (featureFlags): boolean => !!featureFlags[FEATURE_FLAGS.SLACK_APP_OAUTH],
        ],
    }),

    listeners(({ actions, values }) => ({
        projectIntegrationsLoaded: () => {
            // When a project-level integration is added/removed, the backend may
            // auto-create a user-level integration. Reload to pick it up.
            actions.loadIntegrations()
        },
        disconnectSlack: async ({ slackUserId }) => {
            try {
                await usersIntegrationsSlackDestroy('@me', slackUserId)
                lemonToast.success('Unlinked your Slack account')
                actions.loadSlackIntegrations()
                // Refresh linkable so the just-unlinked workspace re-appears
                // in the connect picker without a page reload.
                actions.loadLinkableSlackWorkspaces()
            } catch {
                lemonToast.error('Could not unlink your Slack account.')
            }
        },
        connectGitHub: async () => {
            try {
                const connectFrom = readConnectFromStorage()
                const body: { connect_from?: 'posthog_code'; team_id?: number } = {}
                if (connectFrom === 'posthog_code') {
                    body.connect_from = 'posthog_code'
                }
                if (values.currentTeam?.id) {
                    body.team_id = values.currentTeam.id
                }
                const response = await usersIntegrationsGithubStartCreate('@me', body)
                window.location.href = response.install_url
            } catch (error: unknown) {
                actions.connectGitHubFailure()
                const message = error instanceof Error && 'detail' in error ? (error as any).detail : undefined
                lemonToast.error(message || 'Could not start GitHub installation.')
            }
        },
        disconnectGitHub: async ({ installationId }) => {
            try {
                await usersIntegrationsGithubDestroy('@me', installationId)
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
            actions.loadSlackIntegrations()
            actions.loadLinkableSlackWorkspaces()
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
                lemonToast.error(describeGithubLinkError(params.get('github_link_error')))
            }

            if (params.has('slack_link_success')) {
                lemonToast.success('Slack connected.')
            } else if (params.has('slack_link_error')) {
                const reason = params.get('slack_link_error') ?? ''
                lemonToast.error(SLACK_LINK_ERROR_MESSAGES[reason] ?? SLACK_LINK_ERROR_FALLBACK)
            }
        },
    })),
])

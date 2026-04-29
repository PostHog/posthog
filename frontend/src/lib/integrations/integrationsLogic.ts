import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router, urlToAction } from 'kea-router'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api, { ApiError, getCookie } from 'lib/api'
import { globalSetupLogic } from 'lib/components/ProductSetup'
import { fromParamsGivenUrl, isKeyOf } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { EmailIntegrationDomainGroupedType, IntegrationKind, IntegrationType } from '~/types'

import { integrationsGithubReposRetrieve } from 'products/integrations/frontend/generated/api'
import type { GitHubRepoApi } from 'products/integrations/frontend/generated/api.schemas'
import { ChannelType } from 'products/workflows/frontend/Channels/MessageChannels'

import type { integrationsLogicType } from './integrationsLogicType'
import { ICONS } from './utils'

function toastApiError(e: unknown): void {
    const detail = e instanceof ApiError ? e.detail : null
    lemonToast.error(detail || 'Something went wrong. Please try again.')
}

export const integrationsLogic = kea<integrationsLogicType>([
    path(['lib', 'integrations', 'integrationsLogic']),
    connect(() => ({
        values: [preflightLogic, ['siteUrlMisconfigured', 'preflight'], teamLogic, ['currentProjectId']],
        actions: [globalSetupLogic, ['markTaskAsCompleted']],
    })),

    actions({
        handleGithubCallback: (searchParams: any) => ({ searchParams }),
        handleOauthCallback: (kind: IntegrationKind, searchParams: any) => ({ kind, searchParams }),
        newGoogleCloudKey: (kind: string, key: File, callback?: (integration: IntegrationType) => void) => ({
            kind,
            key,
            callback,
        }),
        deleteIntegration: (id: number) => ({ id }),
        openNewIntegrationModal: (kind: IntegrationKind) => ({ kind }),
        closeNewIntegrationModal: true,
        openSetupModal: (integration?: IntegrationType, channelType?: ChannelType) => ({ integration, channelType }),
        closeSetupModal: true,
        loadGitHubRepositories: (integrationId: number) => ({ integrationId }),
        loadGitHubRepositoriesPage: (integrationId: number, offset: number) => ({ integrationId, offset }),
        loadGitHubRepositoriesPageSuccess: (
            integrationId: number,
            repositories: GitHubRepoApi[],
            hasMore: boolean
        ) => ({
            integrationId,
            repositories,
            hasMore,
        }),
        loadGitHubRepositoriesPageFailure: (integrationId: number) => ({ integrationId }),
    }),
    reducers({
        newIntegrationModalKind: [
            null as IntegrationKind | null,
            {
                openNewIntegrationModal: (_, { kind }: { kind: IntegrationKind }) => kind,
                closeNewIntegrationModal: () => null,
            },
        ],
        setupModalOpen: [
            false,
            {
                openSetupModal: () => true,
                closeSetupModal: () => false,
            },
        ],
        setupModalType: [
            null as ChannelType | null,
            {
                openSetupModal: (_, { channelType }) => channelType ?? null,
                closeSetupModal: () => null,
            },
        ],
        selectedIntegration: [
            null as IntegrationType | null,
            {
                openSetupModal: (_, { integration }) => integration ?? null,
                closeSetupModal: () => null,
            },
        ],
        githubRepositories: [
            {} as Record<number, GitHubRepoApi[]>,
            {
                loadGitHubRepositories: (state, { integrationId }) => ({
                    ...state,
                    [integrationId]: [],
                }),
                loadGitHubRepositoriesPageSuccess: (state, { integrationId, repositories }) => {
                    const existing = state[integrationId] || []
                    const seenIds = new Set(existing.map((r) => r.id))
                    const newRepos = repositories.filter((r) => !seenIds.has(r.id))
                    return { ...state, [integrationId]: [...existing, ...newRepos] }
                },
            },
        ],
        githubRepositoriesLoading: [
            false,
            {
                loadGitHubRepositories: () => true,
                loadGitHubRepositoriesPageSuccess: (_, { hasMore }) => hasMore,
                loadGitHubRepositoriesPageFailure: () => false,
            },
        ],
    }),
    loaders(({ values }) => ({
        integrations: [
            null as IntegrationType[] | null,
            {
                loadIntegrations: async () => {
                    const res = await api.integrations.list()

                    // Simple modifier here to add icons and names - we can move this to the backend at some point

                    return res.results.map((integration) => {
                        return {
                            ...integration,
                            // TODO: Make the icons endpoint independent of hog functions
                            icon_url: ICONS[integration.kind],
                        }
                    })
                },
                newGoogleCloudKey: async ({ kind, key, callback }) => {
                    try {
                        const formData = new FormData()
                        formData.append('kind', kind)
                        formData.append('key', key)
                        const response = await api.integrations.create(formData)
                        const responseWithIcon = {
                            ...response,
                            icon_url: isKeyOf(kind, ICONS) ? ICONS[kind] : ICONS['google-pubsub'],
                        }

                        // run onChange after updating the integrations loader
                        window.setTimeout(() => callback?.(responseWithIcon), 0)

                        if (
                            values.integrations?.find(
                                (x) => x.kind === kind && x.display_name === response.display_name
                            )
                        ) {
                            lemonToast.success('Google Cloud key updated.')
                            return values.integrations.map((x) =>
                                x.kind === kind && x.display_name === response.display_name ? responseWithIcon : x
                            )
                        }
                        lemonToast.success('Google Cloud key created.')
                        return [...(values.integrations ?? []), responseWithIcon]
                    } catch (e) {
                        lemonToast.error('Failed to upload Google Cloud key.')
                        throw e
                    }
                },
            },
        ],
    })),
    listeners(({ actions, values }) => ({
        loadGitHubRepositories: ({ integrationId }) => {
            actions.loadGitHubRepositoriesPage(integrationId, 0)
        },
        loadGitHubRepositoriesPageSuccess: ({ integrationId, hasMore }) => {
            if (hasMore) {
                const currentRepos = values.githubRepositories[integrationId] || []
                actions.loadGitHubRepositoriesPage(integrationId, currentRepos.length)
            }
        },
        loadGitHubRepositoriesPage: async ({ integrationId, offset }, breakpoint) => {
            try {
                const response = await integrationsGithubReposRetrieve(String(values.currentProjectId), integrationId, {
                    limit: 100,
                    offset,
                })
                await breakpoint()
                actions.loadGitHubRepositoriesPageSuccess(integrationId, response.repositories, response.has_more)
            } catch {
                actions.loadGitHubRepositoriesPageFailure(integrationId)
            }
        },
        handleGithubCallback: async ({ searchParams }) => {
            const { state, installation_id, code } = searchParams
            const { next, token, source } = fromParamsGivenUrl(state ?? '')
            const stateToken = token || state

            // User-level GitHub flow (personal integrations / UserIntegration): redirect to the
            // backend endpoint which handles UserIntegration creation server-side.
            if (source === 'user_integration') {
                const backendUrl = combineUrl('/complete/github-link/', {
                    installation_id,
                    code,
                    state: stateToken,
                }).url
                window.location.href = backendUrl
                return
            }

            let replaceUrl: string = next || urls.settings('project-integrations')

            try {
                if (installation_id) {
                    if (stateToken !== getCookie('ph_github_state')) {
                        throw new Error('Invalid state token')
                    }

                    const integration = await api.integrations.create({
                        kind: 'github',
                        config: { installation_id, state: stateToken, code },
                    })

                    // Forward the ids so the `next` landing page (e.g. the PostHog Code
                    // deep link) knows which install was just completed.
                    replaceUrl = combineUrl(replaceUrl, {
                        installation_id: String(installation_id),
                        integration_id: String(integration.id),
                    }).url

                    actions.loadIntegrations()
                    lemonToast.success(`Integration successful.`)
                } else {
                    // If the requesting user does not have permissions an installation_id will not be returned
                    // we assume in this situation that a request has been made to the GitHub organization owners
                    lemonToast.info(
                        'Your request to connect to GitHub has been sent to the organization owners. They will need to complete the installation.'
                    )
                }
            } catch (e) {
                toastApiError(e)
                const detail = e instanceof ApiError ? e.detail : null
                replaceUrl = combineUrl(replaceUrl, {
                    error: 'github_install_failed',
                    error_message: detail || (e instanceof Error ? e.message : 'Unknown error'),
                }).url
            } finally {
                router.actions.replace(replaceUrl)
            }
        },
        handleOauthCallback: async ({ kind, searchParams }) => {
            const { state, code, error, stripe_user_id, account_id, user_id } = searchParams
            const { next, token, source, server_id, kind: stateKind } = fromParamsGivenUrl(state)
            // slack-posthog-code reuses /integrations/slack/callback as its approved redirect URI,
            // so the real kind is carried in OAuth state and takes precedence over the URL path.
            const resolvedKind = (stateKind as IntegrationKind) || kind
            let replaceUrl: string = next || urls.settings('project-integrations')

            if (error) {
                lemonToast.error(`Failed due to "${error}"`)
                router.actions.replace(replaceUrl)
                return
            }

            // Stripe marketplace installs redirect here without a PostHog-minted state, so we
            // can't verify the callback against a CSRF cookie. Without that, an attacker could
            // capture their own Connect-OAuth callback URL and trick a logged-in PostHog admin
            // into visiting it, silently linking the attacker's Stripe account to the victim's
            // team. Redirect to a confirmation page that shows the user the Stripe account
            // they're about to link, and only POST to /integrations/ on explicit confirm.
            // resolvedKind is typed as IntegrationKind which doesn't list 'stripe' in the enum,
            // but the URL route (`/integrations/:kind/callback`) passes it through verbatim.
            const isStripeMarketplaceInstall =
                (resolvedKind as string) === 'stripe' && !state && !!stripe_user_id && !!code

            if (isStripeMarketplaceInstall) {
                const params = new URLSearchParams({
                    code: String(code),
                    stripe_user_id: String(stripe_user_id),
                })
                if (account_id) {
                    params.set('account_id', String(account_id))
                }
                if (user_id) {
                    params.set('user_id', String(user_id))
                }
                router.actions.replace(`${urls.stripeConfirmInstall()}?${params.toString()}`)
                return
            }

            try {
                if (token !== getCookie('ph_oauth_state')) {
                    throw new Error('Invalid state token')
                }

                if (source === 'mcp_store') {
                    replaceUrl += `${replaceUrl.includes('?') ? '&' : '?'}code=${encodeURIComponent(code)}&server_id=${encodeURIComponent(server_id)}&state_token=${encodeURIComponent(token)}`
                    lemonToast.success('Authorization successful.')
                } else {
                    const integration = await api.integrations.create({
                        kind: resolvedKind,
                        config: { state, code },
                    })

                    // Add the integration ID to the replaceUrl so that the landing page can use it
                    const url = new URL(replaceUrl, window.location.origin)
                    url.searchParams.set('integration_id', String(integration.id))
                    replaceUrl = url.pathname + url.search + url.hash

                    actions.loadIntegrations()
                    lemonToast.success(`Integration successful.`)
                }
            } catch (e) {
                toastApiError(e)
            } finally {
                router.actions.replace(replaceUrl)
            }
        },

        deleteIntegration: async ({ id }) => {
            const integration = values.integrations?.find((x) => x.id === id)
            if (!integration) {
                return
            }

            LemonDialog.open({
                title: `Do you want to disconnect from this ${integration.kind} integration?`,
                description:
                    'This cannot be undone. PostHog resources configured to use this integration will remain but will stop working.',
                primaryButton: {
                    children: 'Yes, disconnect',
                    status: 'danger',
                    onClick: async () => {
                        await api.integrations.delete(id)
                        actions.loadIntegrations()
                    },
                },
                secondaryButton: {
                    children: 'No thanks',
                },
            })
        },
    })),
    afterMount(({ actions }) => {
        actions.loadIntegrations()
    }),

    urlToAction(({ actions }) => ({
        '/integrations/github/callback': (_, searchParams) => {
            actions.handleGithubCallback(searchParams)
        },
        '/integrations/:kind/callback': ({ kind = '' }, searchParams) => {
            actions.handleOauthCallback(kind as IntegrationKind, searchParams)
        },
    })),
    selectors({
        slackIntegrations: [
            (s) => [s.integrations],
            (integrations) => {
                return integrations?.filter((x) => x.kind == 'slack')
            },
        ],
        posthogCodeSlackIntegrations: [
            (s) => [s.integrations],
            (integrations) => {
                return integrations?.filter((x) => x.kind === 'slack-posthog-code')
            },
        ],
        getIntegrationsByKind: [
            (s) => [s.integrations],
            (integrations) => {
                return (kinds: IntegrationKind[]) => integrations?.filter((i) => kinds.includes(i.kind)) || []
            },
        ],

        slackAvailable: [
            (s) => [s.preflight],
            (preflight) => {
                // TODO: Change this to be based on preflight or something
                return preflight?.slack_service?.available
            },
        ],
        posthogCodeSlackAvailable: [
            (s) => [s.preflight],
            (preflight) => {
                return preflight?.posthog_code_slack_service?.available
            },
        ],
        getGitHubRepositories: [
            (s) => [s.githubRepositories],
            (githubRepositories) => {
                return (integrationId: number) => (githubRepositories[integrationId] || []).map((r) => r.name)
            },
        ],
        getGitHubRepositoriesFull: [
            (s) => [s.githubRepositories],
            (githubRepositories) => {
                return (integrationId: number): GitHubRepoApi[] => githubRepositories[integrationId] || []
            },
        ],

        domainGroupedEmailIntegrations: [
            (s) => [s.integrations],
            (integrations): EmailIntegrationDomainGroupedType[] => {
                const domainGroupedIntegrations: Record<string, EmailIntegrationDomainGroupedType> = {}

                integrations
                    ?.filter((x) => x.kind === 'email')
                    .forEach((integration) => {
                        const domain = integration.config.domain
                        if (!domainGroupedIntegrations[domain]) {
                            domainGroupedIntegrations[domain] = {
                                domain,
                                integrations: [],
                            }
                        }
                        domainGroupedIntegrations[domain].integrations.push(integration)
                    })

                return Object.values(domainGroupedIntegrations)
            },
        ],
    }),
])

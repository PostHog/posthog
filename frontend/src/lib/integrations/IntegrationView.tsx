import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, Tooltip } from '@posthog/lemon-ui'

import api from 'lib/api'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TZLabel } from 'lib/components/TZLabel'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { TeamMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { GitHubRepoSummary } from 'lib/integrations/GitHubRepoSummary'
import { IntegrationScopesWarning } from 'lib/integrations/IntegrationScopesWarning'
import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { IntegrationType } from '~/types'

import { integrationsLogic } from './integrationsLogic'
import { getIntegrationNameFromKind } from './utils'

function integrationUsageSummary(integration: IntegrationType): string | null {
    if (!integration.usage) {
        return null
    }
    const { destinations, workflows, sources } = integration.usage
    const parts = [
        destinations > 0 ? pluralize(destinations, 'destination') : null,
        workflows > 0 ? pluralize(workflows, 'workflow') : null,
        sources > 0 ? pluralize(sources, 'source') : null,
    ].filter(Boolean)
    if (parts.length === 0) {
        return 'Not used by any destinations, workflows or sources'
    }
    return `Used by ${parts.join(', ')}`
}

export function IntegrationView({
    integration,
    suffix,
    schema,
}: {
    integration: IntegrationType
    suffix?: JSX.Element
    schema?: { requiredScopes?: string }
}): JSX.Element {
    const { deleteIntegration } = useActions(integrationsLogic)
    const { currentTeam } = useValues(teamLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    const errors = (integration.errors && integration.errors?.split(',')) || []
    const { githubRepositoriesLoading, getGitHubRepositories } = useValues(integrationsLogic)
    const { loadGitHubRepositories } = useActions(integrationsLogic)

    const isGitHub = integration.kind === 'github'
    const repositories = isGitHub ? getGitHubRepositories(integration.id) : []
    const refreshedAtTimestamp = integration.config?.refreshed_at || null

    useEffect(() => {
        if (isGitHub) {
            loadGitHubRepositories(integration.id)
        }
    }, [isGitHub, integration.id, loadGitHubRepositories])

    suffix = suffix || (
        <div className="flex flex-row gap-2">
            <LemonButton
                type="secondary"
                status="danger"
                onClick={() => deleteIntegration(integration.id)}
                icon={<IconTrash />}
                disabledReason={restrictedReason}
            >
                Disconnect
            </LemonButton>
        </div>
    )

    const integrationName = getIntegrationNameFromKind(integration.kind)
    const usageSummary = integrationUsageSummary(integration)

    return (
        <div className="rounded border bg-surface-primary">
            <div className="flex flex-wrap justify-between items-center p-2 gap-2">
                <div className="flex gap-4 items-center ml-2">
                    <img
                        src={integration.icon_url}
                        alt={`Integration for ${integrationName}`}
                        title={integrationName}
                        className="w-10 h-10 rounded"
                    />
                    <div>
                        <div className="flex gap-2">
                            <span>
                                {refreshedAtTimestamp ? (
                                    <Tooltip
                                        title={
                                            <div className="flex gap-1 items-baseline">
                                                Last refreshed <TZLabel time={dayjs.unix(refreshedAtTimestamp)} />
                                            </div>
                                        }
                                    >
                                        <strong className="cursor-help underline">Connected</strong>
                                    </Tooltip>
                                ) : (
                                    <>Connected</>
                                )}{' '}
                                to <strong>{integration.display_name}</strong>
                            </span>
                        </div>
                        {integration.created_by ? (
                            <div className="flex items-center">
                                <UserActivityIndicator
                                    at={integration.created_at}
                                    by={integration.created_by}
                                    prefix="Created"
                                    className="text-secondary"
                                />
                            </div>
                        ) : null}
                        {usageSummary ? <div className="text-secondary text-xs">{usageSummary}</div> : null}
                        {isGitHub && (
                            <GitHubRepoSummary
                                repoNames={repositories}
                                loading={githubRepositoriesLoading}
                                installationId={integration.config?.installation_id}
                                accountType={integration.config?.account?.type}
                                accountName={integration.config?.account?.name}
                                onBeforeManage={
                                    currentTeam?.id
                                        ? async () => {
                                              await api.create(
                                                  `api/projects/${currentTeam.id}/integrations/github/prepare_callback/`,
                                                  {
                                                      next: urls.project(
                                                          currentTeam.id,
                                                          urls.settings('project-integrations')
                                                      ),
                                                      installation_id: integration.config?.installation_id,
                                                  }
                                              )
                                          }
                                        : undefined
                                }
                            />
                        )}
                    </div>
                </div>

                {suffix}
            </div>

            {errors.length > 0 ? (
                <div className="p-2">
                    <LemonBanner
                        type="error"
                        action={{
                            children: 'Reconnect',
                            disableClientSideRouting: true,
                            to: api.integrations.authorizeUrl({
                                kind: integration.kind,
                                next: window.location.pathname,
                            }),
                            disabledReason: restrictedReason,
                        }}
                    >
                        {errors[0] === 'TOKEN_REFRESH_FAILED'
                            ? 'Authentication token could not be refreshed. You can reconnect this account or disconnect it and connect a different one.'
                            : `There was an error with this integration: ${errors[0]}`}
                    </LemonBanner>
                </div>
            ) : (
                <IntegrationScopesWarning integration={integration} schema={schema} />
            )}
        </div>
    )
}
